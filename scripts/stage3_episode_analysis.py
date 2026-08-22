"""Stage 3 — the episode engine: full friction accounting on validation.

Models compared (every results table includes the named reference):
  Blocklist  score := 1[transaction's UID has a known fraud >= 7 days old]
             — nothing else. The cleanest statement of the metric-distortion
             claim. Its natural alert set is score==1 (budget = its size).
  A          Baseline A (frozen Stage 1)
  A+beh      B minus label features (behavioural windows only)
  A+fam      A + the 55-feature point-in-time UID aggregation family
  B          A + behavioural + label-derived (the blocklist-echo model)

Roles are computed on the GLOBAL modeling stream (days 1-150) under the
fixed pooled-UID convention, then sliced to validation. Deliverables:
  A. episode table across the alert-budget curve, paired CIs at the primary
     budget (uid-cluster bootstrap)
  B. does the UID family's +0.007 AP buy first-strike recall?
  C. novelty segmentation (uid seen before day 120 vs not) + the
     behavioural-harm mechanism check
  D. entity-key sensitivity: uid / card1 / card1+P_emaildomain
  E. top-scored false-positive dump for hand inspection
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from strikeone import config, entity, episodes
from strikeone import metrics as M

OUT = config.REPORTS / "stage3"
BUDGETS = [500, 1000, 1500, 2000, 2810, 4000, 6000, 8000]
PRIMARY = 2810
N_BOOT = 1000


def episode_row(roles, alert, amount, y):
    r = episodes.friction_accounting(roles, alert, amount)
    prop = roles == episodes.ROLE_PROPAGATED
    return {
        "alerts": r.n_alerts,
        "fs_catch": r.first_strike_catches,
        "redundant": r.redundant,
        "false_pos": r.false_positives,
        "fs_precision(friction_eff)": round(r.friction_efficiency, 4),
        "fs_recall": round(r.first_strike_recall, 4),
        "lw_fs_recall": round(r.loss_weighted_fs_recall, 4),
        "prop_recall": round(float(alert[prop].mean()), 4) if prop.any() else np.nan,
        "redundancy_rate": round(r.redundancy_rate, 4),
        "txn_precision": round(float(y[alert].mean()), 4) if alert.any() else np.nan,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day", "day_idx", "isFraud",
                 "TransactionAmt", "card1", "addr1", "D1", "P_emaildomain",
                 "DeviceInfo", "ProductCD", "C1", "C13", "D2"],
    )
    uid, _ = entity.build_uid(df)
    df["uid"] = uid
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()

    # blocklist flag (delayed, uid-keyed) on the full stream
    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    blocklist_all = (np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0).astype(float)

    va = ((df["day_idx"] >= 120) & (df["day_idx"] <= 147)).to_numpy()
    val = df[va]
    y = val["isFraud"].to_numpy()
    amt = val["TransactionAmt"].to_numpy()
    uid_val = val["uid"].to_numpy()

    # scores from caches, alignment asserted
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage2_val_scores.parquet")
    fam = pd.read_parquet(config.REPO_ROOT / "models" / "stage2_afam_scores.parquet")
    ids = val["TransactionID"].to_numpy()
    assert (sc["TransactionID"].to_numpy() == ids).all()
    assert (fam["TransactionID"].to_numpy() == ids).all()
    assert (sc["y"].to_numpy() == y).all()
    scores = {
        "Blocklist": blocklist_all[va],
        "A": sc["score_a"].to_numpy(),
        "A+beh": sc["score_abeh"].to_numpy(),
        "A+fam": fam["score_afam"].to_numpy(),
        "B": sc["score_b"].to_numpy(),
    }

    # global roles under each entity key (D: sensitivity)
    def key_series(name):
        if name == "uid":
            return df["uid"]
        if name == "card1":
            return df["card1"].astype("int64").astype(str)
        if name == "card1+email":
            em = df["P_emaildomain"].astype(object).where(
                df["P_emaildomain"].notna(), "nan"
            )
            return df["card1"].astype("int64").astype(str) + "_" + em.astype(str)
        raise ValueError(name)

    roles_by_key = {}
    for kname in ["uid", "card1", "card1+email"]:
        roles_by_key[kname] = episodes.episode_roles(
            key_series(kname).to_numpy(), t, y_all, tiebreak=tb
        )[va]
    roles = roles_by_key["uid"]

    out = {}

    # ---- headline metrics incl. Blocklist --------------------------------
    head = {}
    for name, s in scores.items():
        head[name] = {
            "ap": M.average_precision(y, s),
            "roc_auc": M.roc_auc(y, s),
        }
    out["headline"] = head
    print("headline (val):",
          {k: {m: round(v2, 4) for m, v2 in v.items()} for k, v in head.items()})

    # ---- A: episode table across the budget curve -------------------------
    rows = []
    for name, s in scores.items():
        if name == "Blocklist":
            alert = s > 0
            rows.append({"model": name, "budget": int(alert.sum()),
                         **episode_row(roles, alert, amt, y)})
            continue
        for b in BUDGETS:
            alert = M.alerts_at_budget(s, b)
            rows.append({"model": name, "budget": b,
                         **episode_row(roles, alert, amt, y)})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "episode_table.csv", index=False)
    print(table[table["budget"] == PRIMARY].to_string(index=False))
    print(table[table["model"] == "Blocklist"].to_string(index=False))

    # ---- paired CIs at the primary budget (uid-cluster bootstrap) --------
    def fsr_fn(alert):
        fs = roles == episodes.ROLE_FIRST_STRIKE
        return lambda idx: (
            float(alert[idx][fs[idx]].mean()) if fs[idx].any() else np.nan
        )

    alerts_primary = {
        n: (s > 0 if n == "Blocklist" else M.alerts_at_budget(s, PRIMARY))
        for n, s in scores.items()
    }
    ci = {}
    for name, alert in alerts_primary.items():
        ci[name] = M.bootstrap_ci(fsr_fn(alert), len(y), N_BOOT, config.SEED,
                                  groups=uid_val)
        print(f"FS recall {name}: {ci[name][0]:.4f} "
              f"[{ci[name][1]:.4f}, {ci[name][2]:.4f}]")
    out["fs_recall_ci_primary"] = ci

    deltas = {}
    for name in ["B", "A+beh", "A+fam", "Blocklist"]:
        d = M.paired_bootstrap_diff(
            fsr_fn(alerts_primary["A"]), fsr_fn(alerts_primary[name]),
            len(y), N_BOOT, config.SEED, groups=uid_val,
        )
        deltas[f"{name} - A"] = d
        print(f"FS recall delta {name}-A: {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] "
              f"p(<=0)={d[3]:.3f}")
    out["fs_recall_paired_deltas"] = deltas

    # ---- C: novelty segmentation ------------------------------------------
    seen_prior = set(df.loc[df["day_idx"] < 120, "uid"])
    known = pd.Series(uid_val).isin(seen_prior).to_numpy()
    seg_rows = []
    for seg_name, m in [("known_entity", known), ("novel_entity", ~known)]:
        for name in ["Blocklist", "A", "B"]:
            alert = alerts_primary[name]
            seg_rows.append({
                "segment": seg_name, "model": name,
                "n": int(m.sum()), "positives": int(y[m].sum()),
                **episode_row(roles[m], alert[m], amt[m], y[m]),
            })
    seg = pd.DataFrame(seg_rows)
    seg.to_csv(OUT / "novelty_segments.csv", index=False)
    print(seg.to_string(index=False))

    # mechanism check: A+beh harm concentration (transaction AP, row bootstrap)
    mech = {}
    for seg_name, m in [("known_entity", known), ("novel_entity", ~known)]:
        yy = y[m]
        sa, sb = scores["A"][m], scores["A+beh"][m]
        d = M.paired_bootstrap_diff(
            lambda i: M.average_precision(yy[i], sa[i]),
            lambda i: M.average_precision(yy[i], sb[i]),
            int(m.sum()), N_BOOT, config.SEED,
        )
        mech[seg_name] = d
        print(f"A+beh - A (AP) in {seg_name}: {d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}]")
    out["beh_harm_by_segment"] = mech

    # ---- D: key sensitivity -----------------------------------------------
    sens_rows = []
    for kname, rr in roles_by_key.items():
        for name in ["A", "B"]:
            alert = alerts_primary[name]
            sens_rows.append({
                "key": kname, "model": name,
                "n_fs_episodes": int((rr == episodes.ROLE_FIRST_STRIKE).sum()),
                "n_propagated": int((rr == episodes.ROLE_PROPAGATED).sum()),
                **episode_row(rr, alert, amt, y),
            })
    sens = pd.DataFrame(sens_rows)
    sens.to_csv(OUT / "key_sensitivity.csv", index=False)
    print(sens.to_string(index=False))

    # ---- E: false-positive dump for hand inspection ------------------------
    uid_frauds_total = df.groupby("uid")["isFraud"].sum()
    card_frauds_total = df.groupby("card1")["isFraud"].sum()
    val_ctx = val.copy()
    val_ctx["uid_total_frauds"] = val_ctx["uid"].map(uid_frauds_total)
    val_ctx["card1_total_frauds"] = val_ctx["card1"].map(card_frauds_total)
    val_ctx["score_B"] = scores["B"]
    val_ctx["score_A"] = scores["A"]
    fp = val_ctx[val_ctx["isFraud"] == 0].nlargest(15, "score_B")[
        ["TransactionID", "day_idx", "TransactionAmt", "ProductCD",
         "P_emaildomain", "DeviceInfo", "card1", "uid",
         "uid_total_frauds", "card1_total_frauds", "C1", "C13", "D2",
         "score_B", "score_A"]
    ]
    fp.to_csv(OUT / "fp_inspection_topB.csv", index=False)
    fp_a = val_ctx[val_ctx["isFraud"] == 0].nlargest(15, "score_A")[fp.columns]
    fp_a.to_csv(OUT / "fp_inspection_topA.csv", index=False)
    print("top-B false positives written; uid_total_frauds distribution:",
          fp["uid_total_frauds"].tolist())

    (OUT / "episode_analysis.json").write_text(
        json.dumps(out, indent=2, default=float)
    )
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
