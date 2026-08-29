"""Second pre-registered holdout access (holdout_prediction.md, commit
67d35f7). Three analyses, ONE unsealing, one new log entry. The shipped
system is frozen; nothing computed here may change it. Unfavourable
results are reported, not acted on.

  1. rank-by-amount + random baselines at matched budgets (k-curve)
  2. label-maturity sweep d in {1,3,7,14,30}, evaluation-side only
  3. cost-claim rebuild: validation-fitted policy vs validation-tuned
     fixed threshold, both evaluated on holdout, per-corner bootstrap CIs

Refuses to run unless the access log holds exactly ONE entry (the Stage 7
access), and asserts exactly TWO at the end.
"""

from __future__ import annotations

import itertools
import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, entity, episodes, features, seal
from strikeone import metrics as M

sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
from stage2_baseline_b import build_entity_features  # noqa: E402

OUT = config.REPORTS / "stage8"
MODELS = config.REPO_ROOT / "models"
PREREG = "67d35f7"
BUDGETS = [500, 1000, 1500, 2000, 3200, 4000, 6000]
PRIMARY_B = 3200
DELAYS = [1, 3, 7, 14, 30]
N_BOOT = 500
COST_BOOT = 400


def predict(booster_path, train_df, target_df, extra_tr=None, extra_tg=None):
    if extra_tr is not None:
        train_df = pd.concat([train_df.reset_index(drop=True),
                              extra_tr.reset_index(drop=True)], axis=1)
        target_df = pd.concat([target_df.reset_index(drop=True),
                               extra_tg.reset_index(drop=True)], axis=1)
    X_tr, X_tg, cols, cats = features.build_matrices(train_df, target_df)
    booster = lgb.Booster(model_file=str(booster_path))
    assert booster.feature_name() == cols, f"feature drift vs {booster_path}"
    return booster.predict(X_tg)


def sys_row(name, alert, y, amt, roles, n_eps, fs, prop):
    hits = int((alert & (y == 1)).sum())
    fs_c = int((alert & fs).sum())
    cov = int((alert & prop).sum())
    fs_amt_all = float(amt[fs].sum())
    return {
        "system": name, "alerts": int(alert.sum()),
        "fs_recall": round(fs_c / n_eps, 4),
        "lw_fs_recall": round(float(amt[alert & fs].sum()) / fs_amt_all, 4),
        "precision": round(hits / max(int(alert.sum()), 1), 4),
        "blocklist_coverable_share": round(cov / hits, 4) if hits else 0.0,
        "false_positives": int(alert.sum()) - hits,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log0 = config.HOLDOUT_ACCESS_LOG.read_text().splitlines()
    assert len(log0) == 1, (
        f"expected exactly 1 prior access-log entry, found {len(log0)}; "
        "this script performs the single pre-registered SECOND access"
    )

    df_model = pd.read_parquet(config.MODELING_PARQUET)

    # -------- preflight: everything holdout-independent, BEFORE unsealing
    for f in ["baseline_a.txt", "lane2_a2.txt", "stage7_b.txt",
              "stage4_scores.parquet"]:
        assert (MODELS / f).exists(), f"missing {f}; rebuild before running"
    frozen = json.loads((config.REPORTS / "stage4" /
                         "shipped_system_frozen.json").read_text())
    iso_x = np.array(frozen["calibration"]["isotonic_x"])
    iso_y = np.array(frozen["calibration"]["isotonic_y"])
    # item-3 validation side: frozen isotonic (val-fitted at Stage 4) and
    # per-corner thresholds tuned on validation ONLY — prepared pre-unseal
    sc_val = pd.read_parquet(MODELS / "stage4_scores.parquet")
    lane2_val = ~sc_val["lane1_flag"].to_numpy()
    p_val = np.interp(sc_val["score_a2"].to_numpy()[lane2_val], iso_x, iso_y)
    y_val = sc_val["y"].to_numpy()[lane2_val]
    amt_map = df_model.set_index("TransactionID")["TransactionAmt"]
    amt_val = amt_map.loc[sc_val["TransactionID"]].to_numpy()[lane2_val]
    assert len(p_val) == len(amt_val)
    taus = np.unique(np.quantile(p_val, np.linspace(0, 1, 101)))

    # ===================== THE ONE (SECOND) UNSEAL ======================
    holdout = seal.load_holdout(
        unseal=True,
        reason=("Second pre-registered access: rank-by-amount/random "
                "baselines, evaluation-side maturity sweep, cost-claim "
                f"rebuild (holdout_prediction.md, commit {PREREG})"),
    )
    # ====================================================================

    df_all = (pd.concat([df_model, holdout], ignore_index=True)
              .sort_values(["TransactionDT", "TransactionID"])
              .reset_index(drop=True))
    uid, _ = entity.build_uid(df_all)
    df_all["uid"] = uid
    t = df_all["TransactionDT"].to_numpy()
    tb = df_all["TransactionID"].to_numpy()
    y_all = df_all["isFraud"].to_numpy()
    d = df_all["day_idx"].to_numpy()
    ho = (d >= 151) & (d <= 182)
    tr112 = (d >= 1) & (d <= 112)

    roles_all = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)
    roles = roles_all[ho]
    y = y_all[ho]
    amt = df_all.loc[ho, "TransactionAmt"].to_numpy()
    uid_ho = uid.to_numpy()[ho]
    fs = roles == episodes.ROLE_FIRST_STRIKE
    prop = roles == episodes.ROLE_PROPAGATED
    n_eps = int(fs.sum())
    n = int(ho.sum())
    days = 32.0

    def flags_at(delay):
        bl = entity.pit_delayed_label_stats(
            uid, t.astype(np.int64), y_all, tb, delay_days=delay, prefix="u")
        return (np.nan_to_num(bl["u_fraud_rate"].to_numpy()) > 0)[ho]

    flag7 = flags_at(7)
    lane2 = ~flag7

    ho_df = df_all[ho]
    print("scoring A, A2, B ...")
    s_a = predict(MODELS / "baseline_a.txt",
                  df_all[tr112].drop(columns=["uid"]),
                  ho_df.drop(columns=["uid"]))
    # A2 was trained on lane-2-eligible train rows (7d flags on full stream)
    bl_full = entity.pit_delayed_label_stats(
        uid, t.astype(np.int64), y_all, tb, delay_days=7, prefix="u")
    flag_all7 = np.nan_to_num(bl_full["u_fraud_rate"].to_numpy()) > 0
    s_a2 = predict(MODELS / "lane2_a2.txt",
                   df_all[tr112 & ~flag_all7].drop(columns=["uid"]),
                   ho_df.drop(columns=["uid"]))
    beh, lab = build_entity_features(df_all.drop(columns=["uid"]))
    ent_feats = pd.concat([beh, lab], axis=1)
    s_b = predict(MODELS / "stage7_b.txt",
                  df_all[tr112].drop(columns=["uid"]),
                  ho_df.drop(columns=["uid"]),
                  extra_tr=ent_feats[tr112], extra_tg=ent_feats[ho])

    p_ho = np.interp(s_a2, iso_x, iso_y)

    res = {"prereg_commit": PREREG}

    # ---------------- item 1: baselines at matched budgets ----------------
    rng = np.random.default_rng(config.SEED)
    s_rand = rng.random(n)
    s_amt = amt.astype(float)
    rows1 = []
    for b in BUDGETS:
        for name, alert in [
            ("random", M.alerts_at_budget(s_rand, b)),
            ("rank-by-amount", M.alerts_at_budget(s_amt, b)),
            ("single-lane A", M.alerts_at_budget(s_a, b)),
            ("single-lane B", M.alerts_at_budget(s_b, b)),
            ("single-lane A2", M.alerts_at_budget(s_a2, b)),
            ("two-lane+A2 (shipped)",
             flag7 | M.alerts_at_budget(np.where(lane2, s_a2, -np.inf),
                                        min(b, int(lane2.sum())))),
        ]:
            rows1.append({"budget": b,
                          **sys_row(name, alert, y, amt, roles, n_eps, fs,
                                    prop)})
    for name, alert in [("blocklist-only (natural N)", flag7)]:
        rows1.append({"budget": int(flag7.sum()),
                      **sys_row(name, alert, y, amt, roles, n_eps, fs, prop)})
    t1 = pd.DataFrame(rows1)
    t1.to_csv(OUT / "baselines_kcurve.csv", index=False)
    prim = t1[t1.budget == PRIMARY_B].set_index("system")
    res["item1_primary"] = {
        "rank_by_amount_lw_fs": float(
            prim.loc["rank-by-amount", "lw_fs_recall"]),
        "shipped_lw_fs": float(
            prim.loc["two-lane+A2 (shipped)", "lw_fs_recall"]),
        "random_lw_fs": float(prim.loc["random", "lw_fs_recall"]),
    }
    print("1.", t1[t1.budget == PRIMARY_B].to_string(index=False))

    # ---------------- item 2: maturity sweep -------------------------------
    rows2 = []
    for delay in DELAYS:
        fl = flags_at(delay)
        l2 = ~fl
        ship = fl | M.alerts_at_budget(np.where(l2, s_a2, -np.inf),
                                       min(PRIMARY_B, int(l2.sum())))
        bb = M.alerts_at_budget(s_b, PRIMARY_B)
        dlt = M.paired_bootstrap_diff(
            lambda i: float(bb[i][fs[i]].mean()) if fs[i].any() else np.nan,
            lambda i: float(ship[i][fs[i]].mean()) if fs[i].any() else np.nan,
            n, N_BOOT, config.SEED, groups=uid_ho)
        cov_hits = int((fl & (y == 1)).sum())
        rows2.append({
            "delay_days": delay,
            "lane1_flags": int(fl.sum()),
            "coverage_of_fraud": round(cov_hits / int(y.sum()), 4),
            "lane1_precision": round(float(y[fl].mean()) if fl.any() else 0.0,
                                     4),
            "shipped_fs_recall": round(float(ship[fs].mean()), 4),
            "B_fs_recall": round(float(bb[fs].mean()), 4),
            "delta_shipped_minus_B": round(dlt[0], 4),
            "delta_ci_lo": round(dlt[1], 4),
            "delta_ci_hi": round(dlt[2], 4),
        })
        print(f"2. d={delay}: {rows2[-1]}")
    t2 = pd.DataFrame(rows2)
    t2.to_csv(OUT / "maturity_sweep.csv", index=False)
    res["item2_reversal"] = bool((t2["delta_shipped_minus_B"] < 0).any())

    # ---------------- item 3: cost-claim rebuild ---------------------------
    # policy inputs are VALIDATION-fitted only: frozen isotonic breakpoints
    # (fit on validation at Stage 4) and per-corner thresholds tuned on
    # validation. Asserted here.
    y2, a2v, p2 = y[lane2], amt[lane2], p_ho[lane2]
    y1, a1v = y[flag7], amt[flag7]
    boot_idx2 = [np.random.default_rng(config.SEED + i).integers(
        0, len(y2), len(y2), dtype=np.int32) for i in range(COST_BOOT)]
    boot_idx1 = [np.random.default_rng(10_000 + i).integers(
        0, len(y1), len(y1), dtype=np.int32) for i in range(COST_BOOT)]

    grid_rows, k_pos = [], 0
    corners = list(itertools.product([0.05, 0.15, 0.25], [0.05, 0.125, 0.20],
                                     [0.60, 0.775, 0.95], [15.0, 30.0, 60.0]))
    for m_, a_, e_, ch_ in corners:
        prm = M.CostParams(m=m_, a=a_, e=e_, c_h=ch_)
        # validation-tuned threshold for this corner
        best_tau, best_c = None, np.inf
        for tau in taus:
            act = np.where(p_val >= tau, M.BLOCK, M.APPROVE)
            c = float(M.realized_cost(y_val, act, amt_val, prm).sum())
            if c < best_c:
                best_c, best_tau = c, tau
        # holdout per-row cost vectors (lane-1 blocked in both systems)
        ecm = M.expected_cost_matrix(p2, a2v, prm)
        cp2 = M.realized_cost(y2, ecm.argmin(axis=1), a2v, prm)
        cf2 = M.realized_cost(
            y2, np.where(p2 >= best_tau, M.BLOCK, M.APPROVE), a2v, prm)
        c1 = M.realized_cost(y1, np.full(len(y1), M.BLOCK), a1v, prm)
        ca2 = M.realized_cost(y2, np.zeros(len(y2)), a2v, prm)
        ca1 = M.realized_cost(y1, np.zeros(len(y1)), a1v, prm)
        point = ((cf2.sum() - cp2.sum())
                 / (ca1.sum() + ca2.sum()))
        deltas = np.array([
            (cf2[i2].sum() - cp2[i2].sum())
            / max(ca1[i1].sum() + ca2[i2].sum(), 1e-9)
            for i1, i2 in zip(boot_idx1, boot_idx2)])
        lo, hi = np.percentile(deltas, [2.5, 97.5])
        excl = lo > 0
        k_pos += int(excl)
        grid_rows.append({"m": m_, "a": a_, "e": e_, "c_h": ch_,
                          "tau_val": float(best_tau),
                          "edge_point": round(float(point), 5),
                          "ci_lo": round(float(lo), 5),
                          "ci_hi": round(float(hi), 5),
                          "ci_excludes_zero": bool(excl)})
    t3 = pd.DataFrame(grid_rows)
    t3.to_csv(OUT / "cost_rebuild_grid.csv", index=False)
    med = float(t3["edge_point"].median())
    q1, q3 = t3["edge_point"].quantile([0.25, 0.75])
    res["item3"] = {
        "k_of_81_ci_excludes_zero": k_pos,
        "median_edge_pct_of_approve_all": round(med * 100, 3),
        "iqr": [round(float(q1) * 100, 3), round(float(q3) * 100, 3)],
        "min_edge": round(float(t3["edge_point"].min()) * 100, 3),
        "counterfactual_assumption": (
            "a blocked fraudulent transaction is assumed fully avoided; a "
            "stepped-up one is avoided with probability e (liability shift "
            "s=0 here). Sensitivity to this assumption is the e (and s) "
            "dimension of the declared grid."),
    }
    print("3.", json.dumps(res["item3"], indent=2))

    (OUT / "access2_results.json").write_text(
        json.dumps(res, indent=2, default=float))

    log = config.HOLDOUT_ACCESS_LOG.read_text().splitlines()
    assert len(log) == 2, f"expected exactly 2 log entries, found {len(log)}"
    print("ACCESS LOG now has exactly two entries:")
    for line in log:
        print(" ", line[:110])


if __name__ == "__main__":
    main()
