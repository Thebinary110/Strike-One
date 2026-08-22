"""Stage 2 D — Baseline B: entity intelligence on top of Baseline A.

Two separately ablatable feature groups (Stage 1 showed they behave
differently and invariant 3 only constrains the second):

  BEHAVIOURAL (no delay): point-in-time window aggregates over card1,
  addr1, P_emaildomain, DeviceInfo and UID at {1,7,30} days — prior count,
  prior mean amount, velocity. 45 features.

  LABEL-DERIVED (7-day delay): per entity, count of prior transactions old
  enough for their label to exist (>=7 days) and the fraud rate among them.
  10 features.

Feature computation runs over the full modeling stream (days 1-150) with
prior-row-only machinery: a validation row at day 130 may use labels of
transactions up to day 123 — including early-validation ones — exactly as
a deployed system would. The MODEL is fit on train days 1-112 only.

Variants, all with Baseline A's protocol (early stopping on val AP):
  A (cached scores)  |  A+beh  |  A+label  |  B = A+beh+label
Paired bootstrap vs A on validation for each.

Also: the Stage 0 delay-gap check — distribution of label-derived risk
features by validation day; if days 120-127 are displaced, the recorded
decision rule applies (drop that week from the Stage 4 calibration fit, or
move the gap).
"""

from __future__ import annotations

import json

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from strikeone import config, data, entity, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage2"
N_BOOT = 1000
KEYS = ["card1", "addr1", "P_emaildomain", "DeviceInfo", "uid"]


def build_entity_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(behavioural, label_derived), aligned to df's row order."""
    uid, _ = entity.build_uid(df)
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    amt = df["TransactionAmt"].to_numpy()
    y = df["isFraud"].to_numpy()

    beh_parts, lab_parts = [], []
    for key in KEYS:
        vals = uid if key == "uid" else df[key]
        beh_parts.append(
            entity.pit_window_aggs(vals, t, amt, tb, prefix=f"beh_{key}")
        )
        lab_parts.append(
            entity.pit_delayed_label_stats(vals, t, y, tb, prefix=f"lab_{key}")
        )
    beh = pd.concat(beh_parts, axis=1)
    lab = pd.concat(lab_parts, axis=1)
    beh.index = df.index
    lab.index = df.index
    return beh, lab


def fit_variant(train_df, val_df, extras_tr, extras_val):
    if extras_tr:
        train_df = pd.concat(
            [train_df.reset_index(drop=True)]
            + [e.reset_index(drop=True) for e in extras_tr],
            axis=1,
        )
        val_df = pd.concat(
            [val_df.reset_index(drop=True)]
            + [e.reset_index(drop=True) for e in extras_val],
            axis=1,
        )
    X_tr, X_val, cols, cats = features.build_matrices(train_df, val_df)
    params = {
        "objective": "binary", "learning_rate": 0.05, "num_leaves": 64,
        "min_child_samples": 100, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 1,
        "n_estimators": 4000, "force_row_wise": True,
        "seed": config.SEED, "n_jobs": 20, "verbose": -1,
    }
    clf = lgb.LGBMClassifier(**params)
    clf.fit(
        X_tr, train_df["isFraud"],
        eval_set=[(X_val, val_df["isFraud"])],
        eval_metric="average_precision",
        categorical_feature=cats,
        callbacks=[lgb.early_stopping(200, verbose=False), lgb.log_evaluation(0)],
    )
    s = clf.predict_proba(X_val, num_iteration=clf.best_iteration_)[:, 1]
    gain = dict(zip(cols, clf.booster_.feature_importance("gain")))
    return s, clf.best_iteration_, gain


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(config.MODELING_PARQUET)
    beh, lab = build_entity_features(df)

    tr = (df["day_idx"] >= 1) & (df["day_idx"] <= 112)
    va = (df["day_idx"] >= 120) & (df["day_idx"] <= 147)
    train_df, val_df = df[tr], df[va]
    y_val = val_df["isFraud"].to_numpy()

    # Baseline A scores from the shared cache (same rows, same order)
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "baseline_a_val_scores.parquet")
    assert (sc["TransactionID"].to_numpy() == val_df["TransactionID"].to_numpy()).all()
    s_a = sc["score"].to_numpy()

    variants = {
        "A+beh": ([beh[tr]], [beh[va]]),
        "A+label": ([lab[tr]], [lab[va]]),
        "B(A+beh+label)": ([beh[tr], lab[tr]], [beh[va], lab[va]]),
    }
    scores = {"A": s_a}
    meta = {}
    for name, (etr, eva) in variants.items():
        print(f"fitting {name} ...")
        s, best_iter, gain = fit_variant(train_df, val_df, etr, eva)
        scores[name] = s
        total = sum(gain.values())
        ent_gain = {c: g for c, g in gain.items()
                    if c.startswith(("beh_", "lab_"))}
        top = sorted(ent_gain.items(), key=lambda kv: -kv[1])[:8]
        meta[name] = {
            "best_iteration": int(best_iter),
            "entity_gain_share": float(sum(ent_gain.values()) / total),
            "top_entity_features": [(c, round(float(g), 0)) for c, g in top],
        }
        print(f"  best_iter={best_iter} entity_gain_share="
              f"{meta[name]['entity_gain_share']:.4f}")

    # ---- metrics + paired tests vs A ------------------------------------
    res = {}
    for name, s in scores.items():
        entry = {}
        for mname, fn in [("ap", M.average_precision), ("roc_auc", M.roc_auc)]:
            entry[mname] = M.bootstrap_ci(
                lambda i: fn(y_val[i], s[i]), len(y_val), N_BOOT, config.SEED
            )
            if name != "A":
                entry[f"{mname}_delta_vs_A"] = M.paired_bootstrap_diff(
                    lambda i: fn(y_val[i], s_a[i]),
                    lambda i: fn(y_val[i], s[i]),
                    len(y_val), N_BOOT, config.SEED,
                )
        res[name] = entry
        ap, auc = entry["ap"], entry["roc_auc"]
        line = (f"{name:16s} AP={ap[0]:.4f} [{ap[1]:.4f},{ap[2]:.4f}]  "
                f"AUC={auc[0]:.4f} [{auc[1]:.4f},{auc[2]:.4f}]")
        if name != "A":
            d = entry["ap_delta_vs_A"]
            line += f"  dAP={d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] p(<=0)={d[3]:.3f}"
        print(line)

    # B vs A+beh: does the label group add anything on top?
    d = M.paired_bootstrap_diff(
        lambda i: M.average_precision(y_val[i], scores["A+beh"][i]),
        lambda i: M.average_precision(y_val[i], scores["B(A+beh+label)"][i]),
        len(y_val), N_BOOT, config.SEED,
    )
    res["B_vs_A+beh_ap"] = d
    print(f"B vs A+beh: dAP={d[0]:+.4f} [{d[1]:+.4f},{d[2]:+.4f}] p(<=0)={d[3]:.3f}")

    # ---- delay-gap check -------------------------------------------------
    lab_val = lab[va].copy()
    lab_val["day_idx"] = val_df["day_idx"].to_numpy()
    rate_cols = [c for c in lab_val.columns if c.endswith("fraud_rate")]
    perday = lab_val.groupby("day_idx")[rate_cols].mean()
    perday.to_csv(OUT / "delay_gap_check_perday.csv")
    fig, ax = plt.subplots(figsize=(9, 4))
    for c in rate_cols:
        ax.plot(perday.index, perday[c], label=c, lw=1)
    ax.axvspan(120, 127, alpha=0.12, color="red", label="days 120-127")
    ax.set_xlabel("validation day")
    ax.set_ylabel("mean label-derived fraud-rate feature")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "fig_delay_gap_check.png", dpi=150)
    early = perday.loc[120:127].mean()
    late = perday.loc[128:].mean()
    print("delay-gap check (mean risk feature, days 120-127 vs 128-147):")
    for c in rate_cols:
        print(f"  {c}: {early[c]:.4f} vs {late[c]:.4f} "
              f"(ratio {early[c]/late[c] if late[c] else float('nan'):.3f})")
    res["delay_gap_check"] = {
        c: {"early_120_127": float(early[c]), "late_128_147": float(late[c])}
        for c in rate_cols
    }

    # per-day AP of B, for the decay comparison
    sB = scores["B(A+beh+label)"]
    days = val_df["day_idx"].to_numpy()
    pd.DataFrame(
        [
            {"day": int(d_), "ap": M.average_precision(y_val[days == d_], sB[days == d_])}
            for d_ in np.unique(days)
        ]
    ).to_csv(OUT / "baseline_b_perday_ap.csv", index=False)

    res["meta"] = meta
    (OUT / "baseline_b.json").write_text(json.dumps(res, indent=2, default=float))

    # cache B scores for later stages
    pd.DataFrame(
        {"TransactionID": val_df["TransactionID"].to_numpy(),
         "score_b": sB, "score_a": s_a, "y": y_val}
    ).to_parquet(config.REPO_ROOT / "models" / "stage2_val_scores.parquet",
                 index=False)

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
