"""Stage 7 preparation — everything trainable WITHOUT the holdout.

Trains and saves, using days <= 150 only (the seal stays closed):
  1. B (Stage 2 recipe: train 1-112, beh+lab features, early stop on val)
     -> models/stage7_b.txt ; val scores asserted to match the Stage 2 cache
  2. SECONDARY A  (Baseline A recipe): nested fit on days 1-133 with early
     stopping on 134-147 to pick the tree count, then refit on days 1-147
     -> models/stage7_secondary_a.txt
  3. SECONDARY A2 (lane-2 recipe): same nested scheme on lane-2-eligible
     rows; isotonic calibration fitted on the nested inner slice 134-147
     -> models/stage7_secondary_a2.txt + reports/stage7/secondary_calibration.json

Calibration is never fitted on the holdout (locked policy C).
"""

from __future__ import annotations

import json
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from strikeone import config, entity, features

sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
from stage2_baseline_b import build_entity_features  # noqa: E402

OUT = config.REPORTS / "stage7"
MODELS = config.REPO_ROOT / "models"

PARAMS = {
    "objective": "binary", "learning_rate": 0.05, "num_leaves": 64,
    "min_child_samples": 100, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 1, "n_estimators": 4000,
    "force_row_wise": True, "seed": config.SEED, "n_jobs": 20, "verbose": -1,
}


def fit(train_df, eval_df=None, n_estimators=None, extra_tr=None, extra_ev=None):
    if extra_tr is not None:
        train_df = pd.concat([train_df.reset_index(drop=True),
                              extra_tr.reset_index(drop=True)], axis=1)
        if eval_df is not None:
            eval_df = pd.concat([eval_df.reset_index(drop=True),
                                 extra_ev.reset_index(drop=True)], axis=1)
    if eval_df is not None:
        X_tr, X_ev, cols, cats = features.build_matrices(train_df, eval_df)
    else:
        X_tr, _, cols, cats = features.build_matrices(train_df, train_df.head(1))
    p = dict(PARAMS)
    if n_estimators is not None:
        p["n_estimators"] = n_estimators
    clf = lgb.LGBMClassifier(**p)
    kw = {}
    if eval_df is not None:
        kw = {"eval_set": [(X_ev, eval_df["isFraud"])],
              "eval_metric": "average_precision",
              "callbacks": [lgb.early_stopping(200, verbose=False),
                            lgb.log_evaluation(0)]}
    clf.fit(X_tr, train_df["isFraud"], categorical_feature=cats, **kw)
    s_ev = (clf.predict_proba(X_ev, num_iteration=clf.best_iteration_)[:, 1]
            if eval_df is not None else None)
    return clf, s_ev


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(config.MODELING_PARQUET)
    uid, _ = entity.build_uid(df)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()
    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    flag = np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0
    d = df["day_idx"].to_numpy()

    # ---- 1. B, exactly the Stage 2 recipe --------------------------------
    print("fitting B (train 1-112, early stop on val) ...")
    beh, lab = build_entity_features(df)
    tr, va = (d >= 1) & (d <= 112), (d >= 120) & (d <= 147)
    clf_b, s_val = fit(df[tr], df[va],
                       extra_tr=pd.concat([beh[tr], lab[tr]], axis=1),
                       extra_ev=pd.concat([beh[va], lab[va]], axis=1))
    cache = pd.read_parquet(MODELS / "stage2_val_scores.parquet")
    diff = np.max(np.abs(cache["score_b"].to_numpy() - s_val))
    print(f"  B val-score reproduction max diff: {diff:.2e}")
    assert diff < 1e-9, "B refit does not reproduce the Stage 2 cache"
    clf_b.booster_.save_model(str(MODELS / "stage7_b.txt"),
                              num_iteration=clf_b.best_iteration_)

    # ---- 2. secondary A ---------------------------------------------------
    print("fitting secondary A (nested 1-133 / 134-147, refit 1-147) ...")
    n133, n147 = (d >= 1) & (d <= 133), (d >= 134) & (d <= 147)
    nested, _ = fit(df[n133], df[n147])
    n_trees_a = int(nested.best_iteration_)
    full, _ = fit(df[(d >= 1) & (d <= 147)], None, n_estimators=n_trees_a)
    full.booster_.save_model(str(MODELS / "stage7_secondary_a.txt"))
    print(f"  secondary A trees: {n_trees_a}")

    # ---- 3. secondary A2 + nested calibration -----------------------------
    print("fitting secondary A2 (lane-2 eligible, nested calibration) ...")
    e = ~flag
    nested2, s_inner = fit(df[n133 & e], df[n147 & e])
    n_trees_a2 = int(nested2.best_iteration_)
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(s_inner, df.loc[n147 & e, "isFraud"])
    full2, _ = fit(df[(d >= 1) & (d <= 147) & e], None, n_estimators=n_trees_a2)
    full2.booster_.save_model(str(MODELS / "stage7_secondary_a2.txt"))
    (OUT / "secondary_calibration.json").write_text(json.dumps({
        "n_trees_a": n_trees_a, "n_trees_a2": n_trees_a2,
        "isotonic_x": [float(v) for v in iso.X_thresholds_],
        "isotonic_y": [float(v) for v in iso.y_thresholds_],
        "fitted_on": "days 134-147 lane-2-eligible (nested inner split)",
    }, indent=2))
    print(f"  secondary A2 trees: {n_trees_a2}")

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty — seal intact")


if __name__ == "__main__":
    main()
