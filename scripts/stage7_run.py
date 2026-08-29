"""Stage 7 — open the holdout EXACTLY ONCE and execute the pre-registered
analysis plan (reports/holdout_prediction.md, committed at 188b471) in its
committed order. Nothing is added or dropped after the numbers are seen.

The script refuses to start unless the access log is empty, calls
seal.load_holdout exactly once, and asserts the log holds exactly one entry
at the end. Everything it needs that is trainable without the holdout was
prepared and saved beforehand by scripts/stage7_prepare.py.

Outputs: reports/stage7/results.json, episode_table.csv, capacity_curves.csv,
data/processed/holdout_replay.parquet (console-compatible; the two counters
are then read through the same console code path used for validation).
"""

from __future__ import annotations

import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, entity, episodes, features, seal
from strikeone import metrics as M

sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
from stage2_baseline_b import build_entity_features  # noqa: E402

OUT = config.REPORTS / "stage7"
MODELS = config.REPO_ROOT / "models"
N_BOOT = 1000
PER_DAY_GRID = [5, 10, 18, 25, 36, 50, 71, 100, 140, 200, 280, 400, 500]

# pre-registered ranges (holdout_prediction.md)
RANGES = {
    "primary_ap": (0.32, 0.48), "primary_auc": (0.86, 0.91),
    "secondary_ap": (0.50, 0.62), "secondary_auc": (0.90, 0.93),
    "b_minus_a_ap": (0.06, 0.14),
    "routing_ratio_18": (1.5, 2.8),
}


def predict(booster_path, train_df, target_df, extra_tr=None, extra_tg=None):
    """Score target rows with a saved booster, rebuilding the train-fitted
    encoding deterministically. Feature list asserted against the model."""
    if extra_tr is not None:
        train_df = pd.concat([train_df.reset_index(drop=True),
                              extra_tr.reset_index(drop=True)], axis=1)
        target_df = pd.concat([target_df.reset_index(drop=True),
                               extra_tg.reset_index(drop=True)], axis=1)
    X_tr, X_tg, cols, cats = features.build_matrices(train_df, target_df)
    booster = lgb.Booster(model_file=str(booster_path))
    assert booster.feature_name() == cols, f"feature drift vs {booster_path}"
    return booster.predict(X_tg)


def fsr(alert, fs):
    return lambda idx: (
        float(alert[idx][fs[idx]].mean()) if fs[idx].any() else np.nan
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log0 = config.HOLDOUT_ACCESS_LOG.read_text()
    assert log0 == "", (
        "access log is not empty — the holdout has already been opened; "
        "refusing to run again (locked policy: opened exactly once)"
    )

    df_model = pd.read_parquet(config.MODELING_PARQUET)

    # ======================= THE ONE UNSEAL ==============================
    holdout = seal.load_holdout(
        unseal=True,
        reason=("Stage 7 final evaluation per pre-registered plan "
                "(reports/holdout_prediction.md, commit 188b471)"),
    )
    # =====================================================================

    df_all = (
        pd.concat([df_model, holdout], ignore_index=True)
        .sort_values(["TransactionDT", "TransactionID"])
        .reset_index(drop=True)
    )
    uid, _ = entity.build_uid(df_all)
    df_all["uid"] = uid  # bookkeeping column; dropped before every matrix
    t = df_all["TransactionDT"].to_numpy()
    tb = df_all["TransactionID"].to_numpy()
    y_all = df_all["isFraud"].to_numpy()
    d = df_all["day_idx"].to_numpy()

    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    flag_all = np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0
    roles_all = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)

    ho = (d >= 151) & (d <= 182)
    tr112 = (d >= 1) & (d <= 112)
    tr147 = (d >= 1) & (d <= 147)
    y = y_all[ho]
    amt = df_all.loc[ho, "TransactionAmt"].to_numpy()
    uid_ho = uid.to_numpy()[ho]
    roles = roles_all[ho]
    flag = flag_all[ho]
    fs = roles == episodes.ROLE_FIRST_STRIKE
    prop = roles == episodes.ROLE_PROPAGATED
    n = int(ho.sum())
    n_days = int(df_all.loc[ho, "day_idx"].nunique())
    n_eps = int(fs.sum())
    print(f"holdout: {n} rows, {n_days} days, {int(y.sum())} positives, "
          f"{n_eps} first-strike episodes, lane-1 {int(flag.sum())}")

    res = {"n_rows": n, "n_days": n_days, "positives": int(y.sum()),
           "n_episodes": n_eps,
           "lane1_rows": int(flag.sum()),
           "lane1_row_share": round(float(flag.mean()), 4),
           "lane1_positive_share": round(float(y[flag].sum() / y.sum()), 4),
           "propagated_share_of_positives": round(float(prop.sum() / y.sum()), 4),
           "novel_uid_row_share_vs_pre151": round(float(
               (~pd.Series(uid_ho).isin(set(uid[d < 151]))).mean()), 4)}

    ho_df = df_all[ho]
    print("scoring: A (frozen) ...")
    s_a = predict(MODELS / "baseline_a.txt", df_all[tr112].drop(columns=["uid"]),
                  ho_df.drop(columns=["uid"]))
    print("scoring: B ...")
    beh, lab = build_entity_features(df_all.drop(columns=["uid"]))
    ent = pd.concat([beh, lab], axis=1)
    s_b = predict(MODELS / "stage7_b.txt", df_all[tr112].drop(columns=["uid"]),
                  ho_df.drop(columns=["uid"]),
                  extra_tr=ent[tr112], extra_tg=ent[ho])
    print("scoring: A2 (frozen, full holdout) ...")
    elig112 = tr112 & ~flag_all
    s_a2 = predict(MODELS / "lane2_a2.txt", df_all[elig112].drop(columns=["uid"]),
                   ho_df.drop(columns=["uid"]))
    print("scoring: secondary A, secondary A2 ...")
    s_sec_a = predict(MODELS / "stage7_secondary_a.txt",
                      df_all[tr147].drop(columns=["uid"]),
                      ho_df.drop(columns=["uid"]))
    elig147 = tr147 & ~flag_all
    s_sec_a2 = predict(MODELS / "stage7_secondary_a2.txt",
                       df_all[elig147].drop(columns=["uid"]),
                       ho_df.drop(columns=["uid"]))

    # ---------------- item 1: primary headline range check -----------------
    def ci(fn, s):
        return M.bootstrap_ci(lambda i: fn(y[i], s[i]), n, N_BOOT, config.SEED)

    ap_a, auc_a = ci(M.average_precision, s_a), ci(M.roc_auc, s_a)
    res["item1_primary_A"] = {
        "ap": ap_a, "auc": auc_a,
        "ap_in_range": RANGES["primary_ap"][0] <= ap_a[0] <= RANGES["primary_ap"][1],
        "auc_in_range": RANGES["primary_auc"][0] <= auc_a[0] <= RANGES["primary_auc"][1],
    }
    print(f"1. A: AP {ap_a[0]:.4f} [{ap_a[1]:.4f},{ap_a[2]:.4f}] "
          f"(range {RANGES['primary_ap']}), AUC {auc_a[0]:.4f} "
          f"[{auc_a[1]:.4f},{auc_a[2]:.4f}] (range {RANGES['primary_auc']})")

    # ---------------- item 2: distortion size ------------------------------
    ap_b, auc_b = ci(M.average_precision, s_b), ci(M.roc_auc, s_b)
    d_ap = M.paired_bootstrap_diff(
        lambda i: M.average_precision(y[i], s_a[i]),
        lambda i: M.average_precision(y[i], s_b[i]), n, N_BOOT, config.SEED)
    res["item2_B"] = {"ap": ap_b, "auc": auc_b, "b_minus_a_ap": d_ap,
                      "in_predicted_range":
                      RANGES["b_minus_a_ap"][0] <= d_ap[0] <= RANGES["b_minus_a_ap"][1]}
    print(f"2. B: AP {ap_b[0]:.4f}, AUC {auc_b[0]:.4f}; "
          f"B-A AP {d_ap[0]:+.4f} [{d_ap[1]:+.4f},{d_ap[2]:+.4f}] "
          f"(predicted +0.06..+0.14)")

    # ---------------- item 3: the inversion --------------------------------
    n_bl = int(flag.sum())
    inv = {}
    for name, alert in [("blocklist", flag),
                        ("A", M.alerts_at_budget(s_a, n_bl)),
                        ("B", M.alerts_at_budget(s_b, n_bl))]:
        inv[name] = {"precision": round(float(y[alert].mean()), 4),
                     "fs_catches": int((alert & fs).sum()),
                     "fs_recall": round(float(alert[fs].mean()), 4)}
    res["item3_inversion_at_N"] = {"N": n_bl, **inv}
    print(f"3. inversion at N={n_bl}:", inv)

    # ---------------- item 4: routing inoculation --------------------------
    b18 = 18 * n_days
    lane2 = ~flag
    al_off = M.alerts_at_budget(s_b, b18)
    s_b_l2 = np.where(lane2, s_b, -np.inf)
    al_on = M.alerts_at_budget(s_b_l2, min(b18, int(lane2.sum())))
    r_off = float(al_off[fs].mean())
    r_on = float(al_on[fs].mean())
    ratio = r_on / r_off if r_off else float("inf")
    res["item4_routing"] = {
        "budget": b18, "fs_recall_off": round(r_off, 4),
        "fs_recall_on": round(r_on, 4), "ratio": round(ratio, 2),
        "in_predicted_range":
        RANGES["routing_ratio_18"][0] <= ratio <= RANGES["routing_ratio_18"][1],
    }
    print(f"4. routing at 18/day ({b18}): off {r_off:.4f} on {r_on:.4f} "
          f"ratio {ratio:.2f}x (predicted 1.5-2.8x)")

    # ---------------- item 5: episode table + counters at 100/day ----------
    b100 = 100 * n_days
    frozen = json.loads(
        (config.REPORTS / "stage4" / "shipped_system_frozen.json").read_text())
    iso_x = np.array(frozen["calibration"]["isotonic_x"])
    iso_y = np.array(frozen["calibration"]["isotonic_y"])
    rows5 = []
    alerts5 = {}
    for name, s, routed in [("two-lane+A2 (shipped)", s_a2, True),
                            ("single-lane B", s_b, False),
                            ("single-lane A", s_a, False),
                            ("blocklist", None, None)]:
        if name == "blocklist":
            alert = flag.copy()
        elif routed:
            sl = np.where(lane2, s, -np.inf)
            alert = M.alerts_at_budget(sl, min(b100, int(lane2.sum())))
        else:
            alert = M.alerts_at_budget(s, b100)
        alerts5[name] = alert
        r = episodes.friction_accounting(roles, alert, amt)
        rows5.append({
            "system": name,
            "model_alerts": int(alert.sum()),
            "fs_catches": r.first_strike_catches
            + (int((flag & fs).sum()) if routed else 0),
            "redundant": r.redundant,
            "false_pos": r.false_positives,
            "fs_recall": round(
                (r.first_strike_catches
                 + (int((flag & fs).sum()) if routed else 0)) / n_eps, 4),
            "friction_eff": round(r.friction_efficiency, 4),
            "redundancy_rate": round(r.redundancy_rate, 4),
            "txn_precision": round(float(y[alert].mean()), 4),
        })
    tbl5 = pd.DataFrame(rows5)
    tbl5.to_csv(OUT / "episode_table.csv", index=False)
    print("5.", tbl5.to_string(index=False))
    d_fs = M.paired_bootstrap_diff(
        fsr(alerts5["single-lane A"], fs), fsr(alerts5["single-lane B"], fs),
        n, N_BOOT, config.SEED, groups=uid_ho)
    res["item5_fs_delta_B_minus_A"] = d_fs
    res["item5_counters_shipped"] = {
        "episodes_stopped_at_strike_one": int(tbl5.iloc[0]["fs_catches"]),
        "of_episodes": n_eps,
        "alerts_on_already_known_bad": int(tbl5.iloc[0]["redundant"]),
        "lane1_handled": int(flag.sum()),
        "lane1_legit_blocked": int((flag & (y == 0)).sum()),
        "false_positives": int(tbl5.iloc[0]["false_pos"]),
    }
    print(f"5. B-A FS delta {d_fs[0]:+.4f} [{d_fs[1]:+.4f},{d_fs[2]:+.4f}]")
    print("5. counters:", res["item5_counters_shipped"])

    # ---------------- item 6: capacity curves ------------------------------
    rows6 = []
    for per_day in PER_DAY_GRID:
        b = per_day * n_days
        for sname, s in [("shipped", s_a2), ("headline", s_b)]:
            for routing in ("on", "off"):
                if routing == "on":
                    sl = np.where(lane2, s, -np.inf)
                    alert = M.alerts_at_budget(sl, min(b, int(lane2.sum())))
                    fs_c = int((alert & fs).sum()) + int((flag & fs).sum())
                else:
                    alert = M.alerts_at_budget(s, b)
                    fs_c = int((alert & fs).sum())
                rows6.append({"per_day": per_day, "scorer": sname,
                              "routing": routing,
                              "fs_recall": round(fs_c / n_eps, 4),
                              "friction_eff": round(fs_c / max(int(alert.sum()), 1), 4)})
    pd.DataFrame(rows6).to_csv(OUT / "capacity_curves.csv", index=False)

    # ---------------- item 7: secondary ------------------------------------
    ap_s, auc_s = ci(M.average_precision, s_sec_a), ci(M.roc_auc, s_sec_a)
    res["item7_secondary_A"] = {
        "ap": ap_s, "auc": auc_s,
        "ap_in_range": RANGES["secondary_ap"][0] <= ap_s[0] <= RANGES["secondary_ap"][1],
        "auc_in_range": RANGES["secondary_auc"][0] <= auc_s[0] <= RANGES["secondary_auc"][1],
        "retraining_delta_ap": round(ap_s[0] - ap_a[0], 4),
    }
    print(f"7. secondary A: AP {ap_s[0]:.4f} [{ap_s[1]:.4f},{ap_s[2]:.4f}] "
          f"(range {RANGES['secondary_ap']}), AUC {auc_s[0]:.4f}; "
          f"retraining delta +{ap_s[0]-ap_a[0]:.4f} AP")
    sl2 = np.where(lane2, s_sec_a2, -np.inf)
    al_sec = M.alerts_at_budget(sl2, min(b100, int(lane2.sum())))
    r_sec = episodes.friction_accounting(roles, al_sec, amt)
    res["item7_secondary_counters"] = {
        "episodes_stopped_at_strike_one": r_sec.first_strike_catches
        + int((flag & fs).sum()),
        "alerts_on_already_known_bad": r_sec.redundant,
        "fs_recall": round((r_sec.first_strike_catches
                            + int((flag & fs).sum())) / n_eps, 4),
    }
    print("7. secondary counters:", res["item7_secondary_counters"])

    # ---------------- item 8: loss-weighted FS recall ----------------------
    r_ship = episodes.friction_accounting(roles, alerts5["two-lane+A2 (shipped)"], amt)
    res["item8_loss_weighted_fs_recall"] = round(r_ship.loss_weighted_fs_recall, 4)
    print(f"8. loss-weighted FS recall (shipped @100/day): "
          f"{r_ship.loss_weighted_fs_recall:.4f} (val reference 0.415)")

    # ---------------- console replay file ----------------------------------
    p_shipped = np.interp(s_a2, iso_x, iso_y)
    prm = M.CostParams(**frozen["cost_params_central"])
    ec = M.expected_cost_matrix(p_shipped, amt, prm)
    action = np.where(flag, M.BLOCK, ec.argmin(axis=1)).astype(np.int8)
    pd.DataFrame({
        "TransactionID": ho_df["TransactionID"].to_numpy(),
        "t": ho_df["TransactionDT"].to_numpy(),
        "day": ho_df["day"].to_numpy(),
        "day_idx": ho_df["day_idx"].to_numpy(),
        "uid": uid_ho, "amount": amt, "y": y, "role": roles,
        "lane1_flag": flag, "s_shipped": s_a2, "s_headline": s_b,
        "p_shipped": p_shipped, "action_central": action,
        "ProductCD": ho_df["ProductCD"].to_numpy(),
        "P_emaildomain": ho_df["P_emaildomain"].to_numpy(),
        "card1": ho_df["card1"].to_numpy(),
    }).to_parquet(config.DATA_PROCESSED / "holdout_replay.parquet", index=False)
    print("holdout_replay.parquet written (console: --data ...)")

    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))

    log = config.HOLDOUT_ACCESS_LOG.read_text().splitlines()
    assert len(log) == 1, f"expected exactly 1 access-log entry, found {len(log)}"
    print("ACCESS LOG (exactly one entry):", log[0])


if __name__ == "__main__":
    main()
