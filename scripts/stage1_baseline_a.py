"""Stage 1 — Baseline A.

LightGBM on transaction + identity features only (no entity aggregates).
Deliberately modest, documented hyperparameters; no search. Fit on train
(days 1-112), evaluate on validation (days 120-147). The holdout stays
sealed and is verified untouched at the end.

Outputs (reports/stage1/):
  baseline_a_metrics.json      AP / ROC-AUC with bootstrap CIs, CPk curve
  baseline_a_perday_ap.csv     per-validation-day AP
  fig_perday_ap.png            the same as a figure
  baseline_a_importances.csv   top gain importances
  baseline_a_frozen.json       params + features + hashes (the freeze)
  models/baseline_a.txt        the booster (gitignored; rebuildable)
"""

from __future__ import annotations

import hashlib
import json

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from strikeone import config, data, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage1"
MODELS = config.REPO_ROOT / "models"

# Modest, documented, unsearched. Rationale:
#   learning_rate 0.05 / up to 4000 trees with early stopping on val AP:
#     capacity set by the data, not by tuning; val is the designated tuning
#     slice (brief Stage 0 table).
#   num_leaves 64, min_child_samples 100: mid-sized trees, conservative leaf
#     support given 390k rows and a 3.4% positive rate.
#   feature_fraction/bagging 0.8: mild decorrelation, competition-default.
#   force_row_wise, fixed seed, single dataset construction: determinism.
LGBM_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 64,
    "min_child_samples": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "n_estimators": 4000,
    "force_row_wise": True,
    "seed": config.SEED,
    "n_jobs": 20,
    "verbose": -1,
}
EARLY_STOPPING_ROUNDS = 200
N_BOOT = 1000


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def train_baseline_a():
    df = pd.read_parquet(config.MODELING_PARQUET)
    train = data.slice_days(df, "train")
    val = data.slice_days(df, "val")
    y_tr = train["isFraud"].to_numpy()
    y_val = val["isFraud"].to_numpy()

    X_tr, X_val, cols, cats = features.build_matrices(train, val)
    print(f"features: {len(cols)} ({len(cats)} categorical)")

    clf = lgb.LGBMClassifier(**LGBM_PARAMS)
    clf.fit(
        X_tr,
        y_tr,
        eval_set=[(X_val, y_val)],
        eval_metric="average_precision",
        categorical_feature=cats,
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False),
            lgb.log_evaluation(0),
        ],
    )
    best_iter = clf.best_iteration_
    print(f"best_iteration: {best_iter}")
    s_val = clf.predict_proba(X_val, num_iteration=best_iter)[:, 1]
    return clf, val, y_val, s_val, cols, cats, best_iter


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(exist_ok=True)
    clf, val, y_val, s_val, cols, cats, best_iter = train_baseline_a()

    # ---- headline metrics with bootstrap CIs ---------------------------
    n = len(y_val)
    ap_fn = lambda idx: M.average_precision(y_val[idx], s_val[idx])
    auc_fn = lambda idx: M.roc_auc(y_val[idx], s_val[idx])
    ap = M.bootstrap_ci(ap_fn, n, n_boot=N_BOOT, seed=config.SEED)
    auc = M.bootstrap_ci(auc_fn, n, n_boot=N_BOOT, seed=config.SEED)
    print(f"val AP      {ap[0]:.4f}  [{ap[1]:.4f}, {ap[2]:.4f}]")
    print(f"val ROC-AUC {auc[0]:.4f}  [{auc[1]:.4f}, {auc[2]:.4f}]")

    card = val["card1"].fillna(-1).to_numpy()
    cpk = M.card_precision_curve(val["day_idx"].to_numpy(), card, y_val, s_val)
    print("Card Precision@k:", {k: round(v, 4) for k, v in cpk.items()})

    # ---- per-day AP -----------------------------------------------------
    days = val["day_idx"].to_numpy()
    rows = []
    for d in np.unique(days):
        m = days == d
        rows.append(
            {
                "day": int(d),
                "n": int(m.sum()),
                "positives": int(y_val[m].sum()),
                "ap": M.average_precision(y_val[m], s_val[m]),
            }
        )
    perday = pd.DataFrame(rows)
    perday.to_csv(OUT / "baseline_a_perday_ap.csv", index=False)
    from scipy.stats import spearmanr  # noqa: PLC0415

    rho, p = spearmanr(perday["day"], perday["ap"])
    h1 = perday[perday["day"] <= 133]["ap"].mean()
    h2 = perday[perday["day"] > 133]["ap"].mean()
    print(f"per-day AP: spearman(day, ap) rho={rho:.3f} p={p:.3f}; "
          f"first-half mean={h1:.4f}, second-half mean={h2:.4f}")

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(perday["day"], perday["ap"], marker="o", ms=3)
    ax.set_xlabel("validation day index")
    ax.set_ylabel("average precision (within day)")
    ax.set_title("Baseline A: per-day AP across validation (days 120-147)")
    fig.tight_layout()
    fig.savefig(OUT / "fig_perday_ap.png", dpi=150)

    # ---- importances ----------------------------------------------------
    imp = pd.DataFrame(
        {"feature": cols, "gain": clf.booster_.feature_importance("gain")}
    ).sort_values("gain", ascending=False)
    imp.head(50).to_csv(OUT / "baseline_a_importances.csv", index=False)
    print("top-20 by gain:")
    print(imp.head(20).to_string(index=False))

    # ---- freeze ----------------------------------------------------------
    model_path = MODELS / "baseline_a.txt"
    clf.booster_.save_model(str(model_path), num_iteration=best_iter)
    frozen = {
        "params": LGBM_PARAMS,
        "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "best_iteration": best_iter,
        "train_days": config.SPLIT_DAYS["train"],
        "val_days": config.SPLIT_DAYS["val"],
        "n_features": len(cols),
        "features": cols,
        "categorical_features": cats,
        "exclusions": features.PERMANENT_EXCLUSIONS,
        "model_sha256": sha256_bytes(model_path.read_bytes()),
    }
    blob = json.dumps(frozen, indent=2, sort_keys=True, default=str)
    (OUT / "baseline_a_frozen.json").write_text(blob)
    print("config hash (sha256 of frozen json):", sha256_bytes(blob.encode()))

    metrics_out = {
        "val_ap": ap,
        "val_roc_auc": auc,
        "card_precision_at_k": cpk,
        "perday_ap_spearman_rho": rho,
        "perday_ap_first_half": h1,
        "perday_ap_second_half": h2,
        "n_boot": N_BOOT,
    }
    (OUT / "baseline_a_metrics.json").write_text(
        json.dumps(metrics_out, indent=2, default=float)
    )

    # ---- holdout still sealed -------------------------------------------
    log = config.HOLDOUT_ACCESS_LOG.read_text()
    print(f"holdout access log entries: {len(log.splitlines())} (must be 0)")
    assert log == "", "holdout was accessed during Stage 1!"


if __name__ == "__main__":
    main()
