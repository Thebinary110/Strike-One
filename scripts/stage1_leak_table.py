"""Stage 1 — the 2x2 leakage table. Diagnostic experiment, NOT the shipped
model; Baseline A stays clean in its own script.

Design: on top of Baseline A's features, add a deliberately MINIMAL aggregate
pair — transaction count and mean TransactionAmt per card1 — computed two
ways, crossed with two split protocols. Same pool of rows everywhere
(train slice ∪ val slice; the gaps stay discarded); same model capacity in
every cell (Baseline A's early-stopped iteration count, no early stopping
here so no cell gets eval-set model selection).

                      whole-dataset aggs        expanding (point-in-time)
  random split        BOTH LEAKS                split leak only
  chronological       aggregation leak only     CORRECT - the honest number

The random split violates brief invariant 1 by design: it exists to measure
the inflation, is labeled as such, and nothing downstream consumes it.

Decomposition (for AP and ROC-AUC):
  split leak   = cell(random,pit)   - cell(chrono,pit)
  agg leak     = cell(chrono,whole) - cell(chrono,pit)
  interaction  = cell(random,whole) - split leak - agg leak - cell(chrono,pit)
  total        = cell(random,whole) - cell(chrono,pit)
"""

from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, data, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage1"
N_BOOT = 1000


def add_aggregates(pool: pd.DataFrame) -> pd.DataFrame:
    """Two aggregate features per variant, on card1 (never null here)."""
    assert pool["card1"].notna().all(), "card1 has nulls; grouping assumption broken"
    pool = pool.sort_values(["TransactionDT", "TransactionID"]).reset_index(drop=True)
    g = pool.groupby("card1")["TransactionAmt"]

    # whole-dataset: computed over ALL pool rows at once (the leak)
    pool["wd_card1_count"] = g.transform("size").astype(np.float32)
    pool["wd_card1_amt_mean"] = g.transform("mean").astype(np.float32)

    # expanding point-in-time: strictly-prior rows of the same card
    prior_count = g.cumcount()
    cumsum = g.cumsum() - pool["TransactionAmt"]
    pool["pit_card1_count"] = prior_count.astype(np.float32)
    pool["pit_card1_amt_mean"] = (
        (cumsum / prior_count.replace(0, np.nan)).astype(np.float32)
    )
    return pool


def run_cell(pool, train_mask, eval_mask, agg_cols, drop_cols, n_estimators):
    train_df = pool[train_mask]
    eval_df = pool[eval_mask]
    X_tr, X_ev, cols, cats = features.build_matrices(
        train_df.drop(columns=drop_cols), eval_df.drop(columns=drop_cols)
    )
    assert all(c in cols for c in agg_cols)
    params = {
        "objective": "binary",
        "learning_rate": 0.05,
        "num_leaves": 64,
        "min_child_samples": 100,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "n_estimators": n_estimators,
        "force_row_wise": True,
        "seed": config.SEED,
        "n_jobs": 20,
        "verbose": -1,
    }
    clf = lgb.LGBMClassifier(**params)
    clf.fit(X_tr, train_df["isFraud"], categorical_feature=cats)
    s = clf.predict_proba(X_ev)[:, 1]

    # Null verification: the aggregate columns must have actually reached
    # the model — present, non-constant, largely non-null — and their gain
    # is reported so "no lift" can be told apart from "never used".
    gain = dict(zip(cols, clf.booster_.feature_importance("gain")))
    total_gain = sum(gain.values())
    agg_diag = {}
    for c in agg_cols:
        col = X_tr[c]
        assert col.nunique(dropna=True) > 1, f"{c} is constant"
        agg_diag[c] = {
            "nonnull_frac_train": round(float(col.notna().mean()), 4),
            "nonnull_frac_eval": round(float(X_ev[c].notna().mean()), 4),
            "n_unique_train": int(col.nunique(dropna=True)),
            "gain": round(float(gain[c]), 1),
            "gain_share": round(float(gain[c] / total_gain), 5),
            "gain_rank": int(
                sorted(gain.values(), reverse=True).index(gain[c]) + 1
            ),
        }
    return eval_df["isFraud"].to_numpy(), s, agg_diag


def ci(y, s, fn):
    return M.bootstrap_ci(
        lambda idx: fn(y[idx], s[idx]), len(y), n_boot=N_BOOT, seed=config.SEED
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((OUT / "baseline_a_frozen.json").read_text())
    n_estimators = int(frozen["best_iteration"])
    print(f"fixed capacity for all cells: {n_estimators} trees")

    df = pd.read_parquet(config.MODELING_PARQUET)
    pool = pd.concat(
        [data.slice_days(df, "train"), data.slice_days(df, "val")]
    )
    pool = add_aggregates(pool)
    n_eval = int((pool["day_idx"] >= config.SPLIT_DAYS["val"][0]).sum())

    chrono_eval = (pool["day_idx"] >= config.SPLIT_DAYS["val"][0]).to_numpy()
    rng = np.random.default_rng(config.SEED)
    rand_eval = np.zeros(len(pool), dtype=bool)
    rand_eval[rng.choice(len(pool), size=n_eval, replace=False)] = True

    wd_cols = ["wd_card1_count", "wd_card1_amt_mean"]
    pit_cols = ["pit_card1_count", "pit_card1_amt_mean"]

    cells = {}
    scores = {}
    agg_diags = {}
    for split_name, eval_mask in [("random", rand_eval), ("chrono", chrono_eval)]:
        for agg_name, keep, drop in [
            ("whole", wd_cols, pit_cols),
            ("pit", pit_cols, wd_cols),
        ]:
            key = f"{split_name}+{agg_name}"
            print(f"training cell {key} ...")
            y, s, diag = run_cell(pool, ~eval_mask, eval_mask, keep, drop, n_estimators)
            scores[key] = (y, s)
            agg_diags[key] = diag
            print(f"  agg diagnostics: {json.dumps(diag)}")
            ap = ci(y, s, M.average_precision)
            auc = ci(y, s, M.roc_auc)
            cells[key] = {"ap": ap, "roc_auc": auc, "n_eval": len(y)}
            print(f"  AP {ap[0]:.4f} [{ap[1]:.4f},{ap[2]:.4f}]  "
                  f"AUC {auc[0]:.4f} [{auc[1]:.4f},{auc[2]:.4f}]")

    # paired deltas on shared eval rows (whole vs pit within each split)
    paired = {}
    for split_name in ["random", "chrono"]:
        y, s_w = scores[f"{split_name}+whole"]
        _, s_p = scores[f"{split_name}+pit"]
        for mname, fn in [("ap", M.average_precision), ("roc_auc", M.roc_auc)]:
            d = M.paired_bootstrap_diff(
                lambda idx: fn(y[idx], s_p[idx]),
                lambda idx: fn(y[idx], s_w[idx]),
                len(y),
                n_boot=N_BOOT,
                seed=config.SEED,
            )
            paired[f"{split_name}: whole-pit ({mname})"] = d

    # decomposition on point estimates
    decomp = {}
    for mname in ["ap", "roc_auc"]:
        c = {k: v[mname][0] for k, v in cells.items()}
        decomp[mname] = {
            "honest (chrono+pit)": c["chrono+pit"],
            "split_leak (random+pit - chrono+pit)": c["random+pit"] - c["chrono+pit"],
            "agg_leak (chrono+whole - chrono+pit)": c["chrono+whole"] - c["chrono+pit"],
            "interaction": c["random+whole"] - c["random+pit"]
            - c["chrono+whole"] + c["chrono+pit"],
            "total_inflation (random+whole - chrono+pit)": c["random+whole"]
            - c["chrono+pit"],
        }

    out = {"cells": cells, "paired_whole_vs_pit": paired, "decomposition": decomp,
           "agg_diagnostics": agg_diags,
           "n_estimators": n_estimators, "n_boot": N_BOOT}
    (OUT / "leak_table.json").write_text(json.dumps(out, indent=2, default=float))

    # screenshot-ready markdown
    def fmt(cell, m):
        p, lo, hi = cells[cell][m]
        return f"{p:.4f} [{lo:.4f}, {hi:.4f}]"

    md = ["# The 2x2 leakage table (IEEE-CIS, minimal card1 aggregates)", ""]
    for mname, label in [("ap", "Average precision"), ("roc_auc", "ROC-AUC")]:
        md += [
            f"## {label}",
            "",
            "| split \\ aggregates | whole-dataset | expanding (point-in-time) |",
            "|---|---|---|",
            f"| **random** | {fmt('random+whole', mname)} ⚠ BOTH LEAKS "
            f"| {fmt('random+pit', mname)} (split leak only) |",
            f"| **chronological** | {fmt('chrono+whole', mname)} (agg leak only) "
            f"| **{fmt('chrono+pit', mname)} ← HONEST** |",
            "",
        ]
        d = decomp[mname]
        md += [f"- split leak: **{d['split_leak (random+pit - chrono+pit)']:+.4f}**",
               f"- aggregation leak: **{d['agg_leak (chrono+whole - chrono+pit)']:+.4f}**",
               f"- interaction: {d['interaction']:+.4f}",
               f"- total inflation: **{d['total_inflation (random+whole - chrono+pit)']:+.4f}**",
               ""]
    (OUT / "leak_table.md").write_text("\n".join(md))
    print("\n".join(md))

    log = config.HOLDOUT_ACCESS_LOG.read_text()
    assert log == "", "holdout was accessed during Stage 1!"
    print(f"holdout access log entries: {len(log.splitlines())} (must be 0)")


if __name__ == "__main__":
    main()
