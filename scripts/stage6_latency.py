"""Stage 6 — p99 scoring latency and throughput on commodity CPU.

Per-transaction path, measured separately:
  feature path : cyclical time features, train-fitted category mapping,
                 1-row frame assembly, UID construction, blocklist lookup
                 (the shipped system's ONLY point-in-time state — a KV set)
  inference    : frozen A2 booster, single-row predict
  decision     : isotonic interpolation + 3-action expected-cost argmin

Honest note baked into the output: the feature path is small NOT because
anything is precomputed away, but because the corrected metric selected a
scorer with no entity aggregates — the only online state a deployment
needs is a blocklist key-value set. Batch throughput is reported too.
"""

from __future__ import annotations

import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, entity, features
from strikeone import metrics as M

OUT = config.REPORTS / "stage6"
N_SINGLE = 2000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(config.MODELING_PARQUET)
    tr = (df["day_idx"] >= 1) & (df["day_idx"] <= 112)
    va = (df["day_idx"] >= 120) & (df["day_idx"] <= 147)

    frozen = json.loads(
        (config.REPORTS / "stage4" / "shipped_system_frozen.json").read_text())
    booster = lgb.Booster(
        model_file=str(config.REPO_ROOT / "models" / "lane2_a2.txt"))
    iso_x = np.array(frozen["calibration"]["isotonic_x"])
    iso_y = np.array(frozen["calibration"]["isotonic_y"])
    prm = M.CostParams(**frozen["cost_params_central"])

    # offline prep a deployment would hold in memory: category dtypes,
    # feature list, blocklist set
    train_raw = df[tr].drop(columns=["isFraud"])
    train_feat = features.add_time_features(train_raw)
    cols = [c for c in features.feature_columns(train_feat)]
    cats = features.categorical_columns(train_feat, cols)
    dtypes = features.fit_categories(train_feat, cats)
    uid_tr, _ = entity.build_uid(df[tr])
    blocklist = set(uid_tr[df.loc[tr, "isFraud"] == 1])

    rng = np.random.default_rng(config.SEED)
    sample_idx = rng.choice(np.flatnonzero(va.to_numpy()), N_SINGLE, replace=False)
    raw_rows = [df.iloc[[i]] for i in sample_idx]  # 1-row frames, dtypes kept

    t_feat, t_inf, t_dec = [], [], []
    for one_raw in raw_rows:
        row = one_raw.iloc[0]
        t0 = time.perf_counter()
        # ---- feature path ----
        one = features.add_time_features(one_raw)
        X = features.apply_categories(one[cols], dtypes)
        d1 = row["D1"]
        fs_day = np.floor(row["day"] - d1) if pd.notna(d1) else float("nan")
        a1 = row["addr1"]
        uid = (f"{int(row['card1'])}_"
               f"{'nan' if pd.isna(a1) else int(a1)}_"
               f"{'nan' if np.isnan(fs_day) else int(fs_day)}")
        flagged = uid in blocklist
        t1 = time.perf_counter()
        # ---- inference ----
        if not flagged:
            s = booster.predict(X, num_threads=1)[0]
        t2 = time.perf_counter()
        # ---- decision ----
        if flagged:
            action = M.BLOCK
        else:
            p = float(np.interp(s, iso_x, iso_y))
            ec = M.expected_cost_matrix([p], [row["TransactionAmt"]], prm)
            action = int(ec.argmin())
        t3 = time.perf_counter()
        t_feat.append(t1 - t0)
        t_inf.append(t2 - t1)
        t_dec.append(t3 - t2)

    def pct(a, q):
        return round(float(np.percentile(np.array(a) * 1000, q)), 3)

    # batch throughput
    val_raw = df[va].drop(columns=["isFraud"])
    Xb = features.apply_categories(
        features.add_time_features(val_raw)[cols], dtypes)
    tb0 = time.perf_counter()
    booster.predict(Xb)
    tput = len(Xb) / (time.perf_counter() - tb0)

    out = {
        "n_single": N_SINGLE,
        "feature_p50_ms": pct(t_feat, 50), "feature_p99_ms": pct(t_feat, 99),
        "inference_p50_ms": pct(t_inf, 50), "inference_p99_ms": pct(t_inf, 99),
        "decision_p50_ms": pct(t_dec, 50), "decision_p99_ms": pct(t_dec, 99),
        "total_p99_ms": pct(np.array(t_feat) + np.array(t_inf) + np.array(t_dec), 99),
        "batch_throughput_rows_per_s": round(tput, 0),
        "cpu": "commodity CPU, single-threaded inference for the single-row path",
        "note": ("feature path is small because the shipped scorer uses no "
                 "entity aggregates; the only online state is a blocklist "
                 "KV set — nothing was precomputed away"),
    }
    (OUT / "latency.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""


if __name__ == "__main__":
    main()
