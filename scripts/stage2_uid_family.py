"""Stage 2 C — the competition-winning UID aggregation family under a
correct chronological split.

The winning solution's family (~45 features): per-UID aggregations of
TransactionAmt (mean/std), D-columns (mean/std), and C/M-column means, with
UID itself excluded from the feature matrix. Validated there under
month-wise GroupKFold and worth +0.011 AUC. Here the family is rebuilt
faithfully but computed POINT-IN-TIME (expanding, prior rows only) and
measured against Baseline A on validation with a paired bootstrap.

Differences from the original, stated: (1) expanding prior-row aggregates
instead of whole-dataset groupby — whole-dataset is the leak we refuse;
(2) our UID stringifies NaN components exactly as the public kernels did;
(3) M-columns are numerified T=1/F=0 for aggregation.

All aggregates are behavioural (label-free): no verification delay applies
(invariant 3 covers label-derived features only).
"""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, data, entity, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage2"
N_BOOT = 1000

AMT_COLS = ["TransactionAmt"]
D_COLS = [f"D{i}" for i in range(1, 16)]
C_COLS = [f"C{i}" for i in range(1, 15)]
M_COLS = [f"M{i}" for i in range(1, 10)]


def build_family(df: pd.DataFrame) -> pd.DataFrame:
    """~45 UID-keyed point-in-time aggregations, in original row order."""
    uid, _ = entity.build_uid(df)
    vals = df[AMT_COLS + D_COLS + C_COLS].copy()
    for m in M_COLS:
        vals[m] = df[m].map({"T": 1.0, "F": 0.0}).astype(np.float64)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    # mean+std for Amt and D-columns; mean only for C and M (the published
    # family used means there)
    ms = entity.pit_expanding_stats(
        uid, t, vals[AMT_COLS + D_COLS], tb, prefix="uidagg", with_std=True
    )
    mo = entity.pit_expanding_stats(
        uid, t, vals[C_COLS + M_COLS], tb, prefix="uidagg", with_std=False
    )
    fam = pd.concat([ms, mo], axis=1)
    fam.index = df.index
    return fam


def fit_eval(train_df, val_df, extra_tr=None, extra_val=None, n_estimators=391):
    if extra_tr is not None:
        train_df = pd.concat([train_df.reset_index(drop=True),
                              extra_tr.reset_index(drop=True)], axis=1)
        val_df = pd.concat([val_df.reset_index(drop=True),
                            extra_val.reset_index(drop=True)], axis=1)
    X_tr, X_val, cols, cats = features.build_matrices(train_df, val_df)
    params = {
        "objective": "binary", "learning_rate": 0.05, "num_leaves": 64,
        "min_child_samples": 100, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 1,
        "n_estimators": n_estimators, "force_row_wise": True,
        "seed": config.SEED, "n_jobs": 20, "verbose": -1,
    }
    clf = lgb.LGBMClassifier(**params)
    clf.fit(X_tr, train_df["isFraud"], categorical_feature=cats)
    s = clf.predict_proba(X_val)[:, 1]
    gain = dict(zip(cols, clf.booster_.feature_importance("gain")))
    return s, gain


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(config.MODELING_PARQUET)
    fam = build_family(df)  # point-in-time on the full modeling stream
    assert "uid" not in df.columns  # UID itself never enters the matrix

    tr_mask = (df["day_idx"] >= 1) & (df["day_idx"] <= 112)
    val_mask = (df["day_idx"] >= 120) & (df["day_idx"] <= 147)
    train_df, val_df = df[tr_mask], df[val_mask]
    fam_tr, fam_val = fam[tr_mask], fam[val_mask]
    y_val = val_df["isFraud"].to_numpy()

    # family sanity: reached-the-model diagnostics (carry-forward 2 lesson)
    nn = fam_val.notna().mean().round(3)
    print(f"family: {fam.shape[1]} features; val non-null fraction "
          f"min={nn.min():.3f} median={nn.median():.3f} max={nn.max():.3f}")

    print("fitting A (baseline features, fixed 391 trees) ...")
    s_a, _ = fit_eval(train_df, val_df)
    print("fitting A + UID family ...")
    s_f, gain = fit_eval(train_df, val_df, fam_tr, fam_val)

    fam_gain = {c: g for c, g in gain.items() if c.startswith("uidagg")}
    total = sum(gain.values())
    top_fam = sorted(fam_gain.items(), key=lambda kv: -kv[1])[:10]
    print(f"family gain share: {sum(fam_gain.values())/total:.4f}")
    print("top family features by gain:",
          [(c, round(g, 0)) for c, g in top_fam[:5]])

    res = {}
    for mname, fn in [("ap", M.average_precision), ("roc_auc", M.roc_auc)]:
        a = M.bootstrap_ci(lambda i: fn(y_val[i], s_a[i]), len(y_val), N_BOOT, config.SEED)
        f = M.bootstrap_ci(lambda i: fn(y_val[i], s_f[i]), len(y_val), N_BOOT, config.SEED)
        d = M.paired_bootstrap_diff(
            lambda i: fn(y_val[i], s_a[i]),
            lambda i: fn(y_val[i], s_f[i]),
            len(y_val), N_BOOT, config.SEED,
        )
        res[mname] = {"A": a, "A_plus_family": f, "paired_delta": d}
        print(f"{mname}: A={a[0]:.4f} [{a[1]:.4f},{a[2]:.4f}]  "
              f"A+fam={f[0]:.4f} [{f[1]:.4f},{f[2]:.4f}]  "
              f"delta={d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] p(<=0)={d[3]:.3f}")

    pd.DataFrame(
        {"TransactionID": val_df["TransactionID"].to_numpy(),
         "score_afam": s_f, "y": y_val}
    ).to_parquet(config.REPO_ROOT / "models" / "stage2_afam_scores.parquet",
                 index=False)

    res["family_n_features"] = int(fam.shape[1])
    res["family_gain_share"] = float(sum(fam_gain.values()) / total)
    res["family_top_gain"] = [(c, float(g)) for c, g in top_fam]
    res["val_nonnull_min_median_max"] = [float(nn.min()), float(nn.median()),
                                         float(nn.max())]
    (OUT / "uid_family.json").write_text(json.dumps(res, indent=2, default=float))

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
