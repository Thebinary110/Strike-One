"""Stage 4 B — retrain lane 2 on lane-2-eligible rows only.

Lane 1: entity already flagged (uid has a known fraud >= 7 days old) ->
blocklist decision. Lane 2: everything else -> model score.

The hypothesis: the current model (A) was trained on all rows, including
flagged-entity rows it will never score in the two-lane system — a large
share of positives with a near-deterministic label. A2 trains Baseline A's
exact recipe on lane-2-eligible train rows only, early-stopped on
lane-2-eligible validation rows, and is compared to A on the lane-2
population with paired tests.

Outputs: models/stage4_scores.parquet (val: flag, y, score_a, score_b,
score_a2), reports/stage4/lane2_retrain.json.
"""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, entity, episodes, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage4"
BUDGETS = [500, 1000, 1500, 2000, 2810, 4000]
PRIMARY = 2810
N_BOOT = 1000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(config.MODELING_PARQUET)
    uid, _ = entity.build_uid(df)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()

    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    flag_all = np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0
    roles_all = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)

    tr = ((df["day_idx"] >= 1) & (df["day_idx"] <= 112)).to_numpy()
    va = ((df["day_idx"] >= 120) & (df["day_idx"] <= 147)).to_numpy()

    out = {
        "lane1_share_train": round(float(flag_all[tr].mean()), 4),
        "lane1_share_val": round(float(flag_all[va].mean()), 4),
        "lane1_positive_share_train": round(
            float(y_all[tr & flag_all].sum() / y_all[tr].sum()), 4
        ),
        "lane1_positive_share_val": round(
            float(y_all[va & flag_all].sum() / y_all[va].sum()), 4
        ),
        # first strikes that land in lane 1 (pooled-entity artifact): the
        # two-lane system blocks them by rule; counted, not hidden
        "val_fs_rows_in_lane1": int(
            ((roles_all == episodes.ROLE_FIRST_STRIKE) & va & flag_all).sum()
        ),
        "val_fs_rows_total": int(
            ((roles_all == episodes.ROLE_FIRST_STRIKE) & va).sum()
        ),
    }
    print(json.dumps(out, indent=2))

    # ---- retrain A's exact recipe on eligible rows ------------------------
    train_df = df[tr & ~flag_all]
    val2_df = df[va & ~flag_all]
    print(f"lane-2 train rows: {len(train_df)} "
          f"(fraud rate {train_df['isFraud'].mean():.4f}); "
          f"lane-2 val rows: {len(val2_df)} "
          f"(fraud rate {val2_df['isFraud'].mean():.4f})")
    X_tr, X_v2, cols, cats = features.build_matrices(train_df, val2_df)
    params = {
        "objective": "binary", "learning_rate": 0.05, "num_leaves": 64,
        "min_child_samples": 100, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 1, "n_estimators": 4000,
        "force_row_wise": True, "seed": config.SEED, "n_jobs": 20,
        "verbose": -1,
    }
    clf = lgb.LGBMClassifier(**params)
    clf.fit(
        X_tr, train_df["isFraud"],
        eval_set=[(X_v2, val2_df["isFraud"])],
        eval_metric="average_precision",
        categorical_feature=cats,
        callbacks=[lgb.early_stopping(200, verbose=False), lgb.log_evaluation(0)],
    )
    out["a2_best_iteration"] = int(clf.best_iteration_)
    s_a2_lane2 = clf.predict_proba(X_v2, num_iteration=clf.best_iteration_)[:, 1]
    clf.booster_.save_model(
        str(config.REPO_ROOT / "models" / "lane2_a2.txt"),
        num_iteration=clf.best_iteration_,
    )

    # ---- compare A vs A2 on the lane-2 population --------------------------
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage2_val_scores.parquet")
    val_ids = df.loc[va, "TransactionID"].to_numpy()
    assert (sc["TransactionID"].to_numpy() == val_ids).all()
    flag_val = flag_all[va]
    lane2_mask = ~flag_val

    y2 = df.loc[va & ~flag_all, "isFraud"].to_numpy()
    s_a_lane2 = sc["score_a"].to_numpy()[lane2_mask]
    roles2 = roles_all[va][lane2_mask]
    uid2 = uid.to_numpy()[va & ~flag_all]
    fs2 = roles2 == episodes.ROLE_FIRST_STRIKE

    out["lane2_ap_A"] = round(M.average_precision(y2, s_a_lane2), 4)
    out["lane2_ap_A2"] = round(M.average_precision(y2, s_a2_lane2), 4)
    out["lane2_auc_A"] = round(M.roc_auc(y2, s_a_lane2), 4)
    out["lane2_auc_A2"] = round(M.roc_auc(y2, s_a2_lane2), 4)
    print(f"lane-2 AP: A {out['lane2_ap_A']}  A2 {out['lane2_ap_A2']}")
    print(f"lane-2 AUC: A {out['lane2_auc_A']}  A2 {out['lane2_auc_A2']}")

    def fsr(alert):
        return lambda idx: (
            float(alert[idx][fs2[idx]].mean()) if fs2[idx].any() else np.nan
        )

    curve = []
    for b in BUDGETS:
        al_a = M.alerts_at_budget(s_a_lane2, b)
        al_a2 = M.alerts_at_budget(s_a2_lane2, b)
        row = {
            "budget": b,
            "fs_recall_A": round(float(al_a[fs2].mean()), 4),
            "fs_recall_A2": round(float(al_a2[fs2].mean()), 4),
            "friction_eff_A": round(float((al_a & fs2).sum() / b), 4),
            "friction_eff_A2": round(float((al_a2 & fs2).sum() / b), 4),
        }
        if b == PRIMARY:
            d = M.paired_bootstrap_diff(
                fsr(al_a), fsr(al_a2), len(y2), N_BOOT, config.SEED, groups=uid2
            )
            row["fs_delta_A2_minus_A"] = [round(x, 4) for x in d]
            dap = M.paired_bootstrap_diff(
                lambda i: M.average_precision(y2[i], s_a_lane2[i]),
                lambda i: M.average_precision(y2[i], s_a2_lane2[i]),
                len(y2), N_BOOT, config.SEED,
            )
            row["ap_delta_A2_minus_A"] = [round(x, 4) for x in dap]
        curve.append(row)
        print(row)
    out["curve"] = curve

    # cache scores for the policy stage
    s_a2_full = np.full(int(va.sum()), np.nan)
    s_a2_full[lane2_mask] = s_a2_lane2
    pd.DataFrame(
        {"TransactionID": val_ids, "lane1_flag": flag_val,
         "y": sc["y"].to_numpy(),
         "score_a": sc["score_a"].to_numpy(),
         "score_b": sc["score_b"].to_numpy(),
         "score_a2": s_a2_full}
    ).to_parquet(config.REPO_ROOT / "models" / "stage4_scores.parquet",
                 index=False)

    (OUT / "lane2_retrain.json").write_text(json.dumps(out, indent=2, default=float))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
