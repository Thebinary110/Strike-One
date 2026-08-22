"""Stage 6 — build the console replay file (VALIDATION ONLY; holdout sealed).

Emits data/processed/console_replay.parquet: one row per evaluation-slice
transaction with everything the console needs — scores for each selectable
scorer, lane flag, global episode role, calibrated probability and central
argmin action for the shipped system. The console computes every displayed
number from this file at request time; nothing is baked into the UI, so
Stage 7 can point the console at a holdout-derived file.

A2 full-slice scores: the Stage 4 cache holds A2 scores only on lane-2 rows
(all it ever scores in deployment). The routing-OFF console mode needs a
full ranking, so A2 is refit here exactly as in stage4_lane2 (deterministic:
same seed, rows, params) and its lane-2 scores are asserted to match the
frozen system's model hash lineage before full-slice prediction.

Usage: uv run python scripts/stage6_prepare_replay.py [--days LO HI]
  --days: optional sub-slice (default 120 147) — also used to verify the
  nothing-hardcoded property by swapping in a different slice.
"""

from __future__ import annotations

import argparse
import json

import lightgbm as lgb
import numpy as np
import pandas as pd

from strikeone import config, entity, episodes, features
from strikeone import metrics as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs=2, type=int, default=[120, 147])
    ap.add_argument("--out", default=str(config.DATA_PROCESSED / "console_replay.parquet"))
    args = ap.parse_args()
    lo, hi = args.days
    assert hi <= 150, "console replay is built from the modeling file only; " \
                      "the holdout stays sealed until Stage 7"

    df = pd.read_parquet(config.MODELING_PARQUET)
    uid, _ = entity.build_uid(df)
    df["uid"] = uid
    t = df["TransactionDT"].to_numpy()
    tb = df["TransactionID"].to_numpy()
    y_all = df["isFraud"].to_numpy()

    bl = entity.pit_delayed_label_stats(uid, t, y_all, tb, prefix="uid")
    flag_all = np.nan_to_num(bl["uid_fraud_rate"].to_numpy()) > 0
    roles_all = episodes.episode_roles(uid.to_numpy(), t, y_all, tiebreak=tb)

    tr = ((df["day_idx"] >= 1) & (df["day_idx"] <= 112)).to_numpy()
    sl = ((df["day_idx"] >= lo) & (df["day_idx"] <= hi)).to_numpy()

    # ---- score the whole slice with the FROZEN A2 booster ------------------
    # (the frozen system is the saved artifact; its sha256 is committed in
    # shipped_system_frozen.json and verified here before any prediction)
    import hashlib

    frozen = json.loads(
        (config.REPORTS / "stage4" / "shipped_system_frozen.json").read_text()
    )
    model_path = config.REPO_ROOT / "models" / "lane2_a2.txt"
    actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert actual_hash == frozen["lane2_model_sha256"], (
        "models/lane2_a2.txt does not match the frozen hash; rebuild it with "
        "scripts/stage4_lane2.py"
    )
    booster = lgb.Booster(model_file=str(model_path))

    # `uid` is a bookkeeping column, never a feature — drop before encoding
    train_df = df[tr & ~flag_all].drop(columns=["uid"])
    slice_df = df[sl]
    X_tr, X_sl, cols, cats = features.build_matrices(
        train_df, slice_df.drop(columns=["uid"])
    )
    assert booster.feature_name() == cols, "feature recipe drifted from the frozen model"
    s_shipped = booster.predict(X_sl)

    # scores for the headline pick (B) and A come from the Stage 4 cache
    # when the slice is the standard validation window; for sub-slices they
    # are subset from it.
    sc = pd.read_parquet(config.REPO_ROOT / "models" / "stage4_scores.parquet")
    cache = sc.set_index("TransactionID")
    ids = slice_df["TransactionID"].to_numpy()
    missing = ~pd.Index(ids).isin(cache.index)
    assert not missing.any(), (
        "replay slice must be inside the validation window covered by the "
        "Stage 4 score cache"
    )
    s_headline = cache.loc[ids, "score_b"].to_numpy()
    # sanity: refit A2 must reproduce the cached lane-2 scores
    cached_a2 = cache.loc[ids, "score_a2"].to_numpy()
    l2 = ~flag_all[sl]
    if l2.any():
        diff = np.nanmax(np.abs(cached_a2[l2] - s_shipped[l2]))
        assert diff < 1e-9, f"A2 refit does not reproduce cached scores (max diff {diff})"

    # calibrated p + central argmin action for the shipped system (frozen map)
    iso_x = np.array(frozen["calibration"]["isotonic_x"])
    iso_y = np.array(frozen["calibration"]["isotonic_y"])
    p_shipped = np.interp(s_shipped, iso_x, iso_y)
    cp = frozen["cost_params_central"]
    prm = M.CostParams(**cp)
    amt = slice_df["TransactionAmt"].to_numpy()
    ec = M.expected_cost_matrix(p_shipped, amt, prm)
    action = np.where(flag_all[sl], M.BLOCK, ec.argmin(axis=1)).astype(np.int8)

    out = pd.DataFrame({
        "TransactionID": ids,
        "t": slice_df["TransactionDT"].to_numpy(),
        "day": slice_df["day"].to_numpy(),
        "day_idx": slice_df["day_idx"].to_numpy(),
        "uid": slice_df["uid"].to_numpy(),
        "amount": amt,
        "y": slice_df["isFraud"].to_numpy(),
        "role": roles_all[sl],
        "lane1_flag": flag_all[sl],
        "s_shipped": s_shipped,
        "s_headline": s_headline,
        "p_shipped": p_shipped,
        "action_central": action,
        "ProductCD": slice_df["ProductCD"].to_numpy(),
        "P_emaildomain": slice_df["P_emaildomain"].to_numpy(),
        "card1": slice_df["card1"].to_numpy(),
    }).sort_values(["t", "TransactionID"]).reset_index(drop=True)
    out.to_parquet(args.out, index=False)
    print(f"replay: {len(out)} rows, days {lo}-{hi}, "
          f"episodes {(out['role'] == episodes.ROLE_FIRST_STRIKE).sum()}, "
          f"lane1 {int(out['lane1_flag'].sum())} -> {args.out}")

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
