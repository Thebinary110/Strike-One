"""Stage 2 carry-forward: decompose the per-day AP decay.

Stage 1 found per-day AP falling across validation (rho=-0.668) and,
separately, identity coverage falling 26.7% (train) -> 17.7% (val). Those
two explanations — model staleness vs missing identity features — are
confounded. This script separates them:

  (a) identity coverage per day, days 1-150: gradual drift or step change?
  (b) per-day AP vs day (staleness) and vs coverage, plus a joint OLS
  (c) headline metrics stratified by identity-present vs identity-absent

Baseline A is retrained from its frozen config (deterministic) and its
validation scores are cached for reuse by the rest of Stage 2.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from strikeone import config, data
from strikeone import metrics as M

OUT = config.REPORTS / "stage2"
SCORE_CACHE = config.REPO_ROOT / "models" / "baseline_a_val_scores.parquet"


def get_val_scores() -> pd.DataFrame:
    """Baseline A validation scores, cached (deterministic retrain if absent)."""
    if SCORE_CACHE.exists():
        return pd.read_parquet(SCORE_CACHE)
    import sys

    sys.path.insert(0, str(config.REPO_ROOT / "scripts"))
    from stage1_baseline_a import train_baseline_a  # noqa: PLC0415

    clf, val, y_val, s_val, cols, cats, best_iter = train_baseline_a()
    out = pd.DataFrame(
        {
            "TransactionID": val["TransactionID"].to_numpy(),
            "day_idx": val["day_idx"].to_numpy(),
            "card1": val["card1"].to_numpy(),
            "TransactionAmt": val["TransactionAmt"].to_numpy(),
            "y": y_val,
            "score": s_val,
        }
    )
    out.to_parquet(SCORE_CACHE, index=False)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sc = get_val_scores()

    # identity membership from the raw identity file (label-free)
    ti = pd.read_csv(config.RAW_IDENTITY, usecols=["TransactionID"])
    id_set = set(ti["TransactionID"])
    sc["has_id"] = sc["TransactionID"].isin(id_set)

    # ---- (a) coverage per day over days 1-150 --------------------------
    df = pd.read_parquet(
        config.MODELING_PARQUET, columns=["TransactionID", "day_idx"]
    )
    df["has_id"] = df["TransactionID"].isin(id_set)
    cov = df.groupby("day_idx")["has_id"].mean()
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(cov.index, cov.values, lw=1)
    for name, (lo, hi) in config.SPLIT_DAYS.items():
        if name in ("delay_gap", "blind_gap"):
            ax.axvspan(lo, hi, alpha=0.15, color="gray")
    ax.set_xlabel("day index")
    ax.set_ylabel("identity-join coverage")
    ax.set_title("Identity coverage per day, days 1-150")
    fig.tight_layout()
    fig.savefig(OUT / "fig_id_coverage_per_day.png", dpi=150)
    cov.to_frame("coverage").to_csv(OUT / "id_coverage_per_day.csv")

    # largest day-over-day changes, to distinguish drift from a step
    dcov = cov.diff().dropna().sort_values()
    print("coverage: 5 largest single-day drops:")
    print((dcov.head(5) * 100).round(2).to_string())
    print("coverage: weekly means (day//7):")
    wk = cov.groupby((cov.index - 1) // 7).mean()
    print((wk * 100).round(2).to_string())

    # ---- (b) per-day AP vs day and vs coverage -------------------------
    rows = []
    for d, g in sc.groupby("day_idx"):
        rows.append(
            {
                "day": int(d),
                "ap": M.average_precision(g["y"], g["score"]),
                "coverage": float(g["has_id"].mean()),
                "n": len(g),
                "positives": int(g["y"].sum()),
            }
        )
    perday = pd.DataFrame(rows)
    perday.to_csv(OUT / "perday_ap_coverage.csv", index=False)

    from scipy import stats  # noqa: PLC0415

    r_day = stats.spearmanr(perday["day"], perday["ap"])
    r_cov = stats.spearmanr(perday["coverage"], perday["ap"])
    r_daycov = stats.spearmanr(perday["day"], perday["coverage"])
    print(f"spearman(day, ap)       rho={r_day.statistic:+.3f} p={r_day.pvalue:.4f}")
    print(f"spearman(coverage, ap)  rho={r_cov.statistic:+.3f} p={r_cov.pvalue:.4f}")
    print(f"spearman(day, coverage) rho={r_daycov.statistic:+.3f} p={r_daycov.pvalue:.4f}")

    # joint OLS on standardized variables (n=28, so indicative only)
    z = lambda v: (v - v.mean()) / v.std()
    X = np.column_stack([z(perday["day"]), z(perday["coverage"]), np.ones(len(perday))])
    beta, *_ = np.linalg.lstsq(X, z(perday["ap"]), rcond=None)
    print(f"joint OLS (standardized): beta_day={beta[0]:+.3f}, "
          f"beta_coverage={beta[1]:+.3f}  (n=28, indicative)")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].scatter(perday["day"], perday["ap"], s=18)
    axes[0].set_xlabel("day"), axes[0].set_ylabel("per-day AP")
    axes[1].scatter(perday["coverage"], perday["ap"], s=18)
    axes[1].set_xlabel("identity coverage (per day)")
    axes[1].set_ylabel("per-day AP")
    fig.suptitle("Per-day AP vs staleness (left) and identity coverage (right)")
    fig.tight_layout()
    fig.savefig(OUT / "fig_ap_vs_day_and_coverage.png", dpi=150)

    # ---- (c) stratified headline metrics -------------------------------
    strat = {}
    for name, mask in [
        ("identity_present", sc["has_id"].to_numpy()),
        ("identity_absent", (~sc["has_id"]).to_numpy()),
    ]:
        y = sc["y"].to_numpy()[mask]
        s = sc["score"].to_numpy()[mask]
        n = int(mask.sum())
        ap = M.bootstrap_ci(
            lambda idx: M.average_precision(y[idx], s[idx]), n, 1000, config.SEED
        )
        auc = M.bootstrap_ci(
            lambda idx: M.roc_auc(y[idx], s[idx]), n, 1000, config.SEED
        )
        strat[name] = {
            "n": n,
            "positives": int(y.sum()),
            "fraud_rate": round(float(y.mean()), 5),
            "ap": ap,
            "roc_auc": auc,
        }
        print(f"{name}: n={n} pos={int(y.sum())} rate={y.mean():.4f} "
              f"AP={ap[0]:.4f} [{ap[1]:.4f},{ap[2]:.4f}] "
              f"AUC={auc[0]:.4f} [{auc[1]:.4f},{auc[2]:.4f}]")

    json_out = {
        "spearman_day_ap": [r_day.statistic, r_day.pvalue],
        "spearman_coverage_ap": [r_cov.statistic, r_cov.pvalue],
        "spearman_day_coverage": [r_daycov.statistic, r_daycov.pvalue],
        "joint_ols_beta_day": float(beta[0]),
        "joint_ols_beta_coverage": float(beta[1]),
        "stratified": strat,
    }
    (OUT / "decay_decomposition.json").write_text(
        json.dumps(json_out, indent=2, default=float)
    )

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
