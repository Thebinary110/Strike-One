"""Stage 2 — mandatory investigation of Baseline B's +0.17 AP.

Hypothesis: the gain is label propagation manifesting as a feature. The
host labels every transaction after an entity's first chargeback as fraud;
therefore "this entity has a known fraud >=7 days old" nearly determines
the label by construction. If so, B's gain concentrates on PROPAGATED
positives (blocklist-coverable) and vanishes on first strikes.

Checks:
  1. structure: share of val positives on entities with visible prior fraud
  2. a pure blocklist score (max of the 5 delayed fraud-rate features,
     no model at all) — its AP/AUC on validation
  3. A vs B within the flagged-visible and fresh subpopulations
  4. first-strike vs propagated recall at a fixed alert budget (=n_pos)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from strikeone import config, entity, episodes
from strikeone import metrics as M

OUT = config.REPORTS / "stage2"


def main():
    df = pd.read_parquet(
        config.MODELING_PARQUET,
        columns=["TransactionID", "TransactionDT", "day", "day_idx", "isFraud",
                 "TransactionAmt", "card1", "addr1", "D1", "P_emaildomain",
                 "DeviceInfo"],
    )
    uid, _ = entity.build_uid(df)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()

    lab = {}
    for key in ["card1", "addr1", "P_emaildomain", "DeviceInfo", "uid"]:
        vals = uid if key == "uid" else df[key]
        lab[key] = entity.pit_delayed_label_stats(
            vals, t, y_all, tb, prefix=key
        )[f"{key}_fraud_rate"].to_numpy()

    # roles on the global stream (days 1-150), per the Stage 0 convention
    roles = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)

    va = ((df["day_idx"] >= 120) & (df["day_idx"] <= 147)).to_numpy()
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage2_val_scores.parquet")
    val_ids = df.loc[va, "TransactionID"].to_numpy()
    assert (sc["TransactionID"].to_numpy() == val_ids).all()
    y = sc["y"].to_numpy()
    s_a, s_b = sc["score_a"].to_numpy(), sc["score_b"].to_numpy()

    rate_mat = np.vstack([np.nan_to_num(lab[k][va]) for k in lab])
    flagged_visible = (rate_mat > 0).any(axis=0)
    blocklist_score = rate_mat.max(axis=0)
    roles_val = roles[va]

    out = {}

    # 1. structure
    pos = y == 1
    out["structure"] = {
        "val_positives": int(pos.sum()),
        "positives_on_flagged_entity": int((pos & flagged_visible).sum()),
        "share_positives_flagged": float(flagged_visible[pos].mean()),
        "share_negatives_flagged": float(flagged_visible[~pos].mean()),
        "roles_in_val": {
            "first_strike": int((roles_val == episodes.ROLE_FIRST_STRIKE).sum()),
            "propagated": int((roles_val == episodes.ROLE_PROPAGATED).sum()),
        },
    }
    print(json.dumps(out["structure"], indent=2))

    # 2. pure blocklist score — no model
    out["blocklist_only"] = {
        "ap": M.average_precision(y, blocklist_score),
        "roc_auc": M.roc_auc(y, blocklist_score),
    }
    print("pure blocklist (max delayed fraud-rate):", out["blocklist_only"])

    # 3. within-subpopulation comparison
    for name, mask in [("flagged_visible", flagged_visible),
                       ("fresh", ~flagged_visible)]:
        sub = {}
        yy = y[mask]
        sub["n"] = int(mask.sum())
        sub["positives"] = int(yy.sum())
        sub["fraud_rate"] = float(yy.mean())
        for lbl, s in [("A", s_a), ("B", s_b)]:
            sub[f"ap_{lbl}"] = M.average_precision(yy, s[mask]) if yy.sum() else None
        d = M.paired_bootstrap_diff(
            lambda i: M.average_precision(yy[i], s_a[mask][i]),
            lambda i: M.average_precision(yy[i], s_b[mask][i]),
            int(mask.sum()), 1000, config.SEED,
        )
        sub["ap_delta_B_minus_A"] = d
        out[f"subpop_{name}"] = sub
        print(name, json.dumps(sub, default=float))

    # 4. first-strike vs propagated recall at budget = n_pos
    budget = int(pos.sum())
    for lbl, s in [("A", s_a), ("B", s_b), ("blocklist", blocklist_score)]:
        alert = M.alerts_at_budget(s, budget)
        fs = roles_val == episodes.ROLE_FIRST_STRIKE
        pr = roles_val == episodes.ROLE_PROPAGATED
        out[f"budget_recall_{lbl}"] = {
            "first_strike_recall": float(alert[fs].mean()),
            "propagated_recall": float(alert[pr].mean()),
            "precision": float(y[alert].mean()),
        }
        print(lbl, out[f"budget_recall_{lbl}"])

    (OUT / "label_gain_investigation.json").write_text(
        json.dumps(out, indent=2, default=float)
    )
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""


if __name__ == "__main__":
    main()
