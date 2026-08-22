"""Stage 2 A+B: UID reconstruction quality and entity novelty.

Everything here is label-free and descriptive. Holdout-slice rows are read
from the RAW transaction stream (as Stage 0's slice table was), never
through the sealed evaluation file; no holdout label is touched and the
seal/access log are unaffected. This is stated in the Stage 2 report.

A: UID resolution rate per slice, null pattern, cardinality,
   transactions-per-UID distribution.
B: entity novelty — share of val/holdout rows whose entity was never seen
   (i) in train (days 1-112), and (ii) in ALL data before the slice starts.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from strikeone import config, entity

OUT = config.REPORTS / "stage2"

KEYS = ["uid", "card1", "addr1", "P_emaildomain", "DeviceInfo"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tt = pd.read_csv(
        config.RAW_TRANSACTION,
        usecols=["TransactionID", "TransactionDT", "card1", "addr1", "D1",
                 "P_emaildomain"],
    )
    ti = pd.read_csv(config.RAW_IDENTITY, usecols=["TransactionID", "DeviceInfo"])
    df = tt.merge(ti, on="TransactionID", how="left")
    df["day"] = df["TransactionDT"] / config.SECONDS_PER_DAY
    df["day_idx"] = np.floor(df["day"]).astype(np.int32)
    df = df.sort_values(["TransactionDT", "TransactionID"]).reset_index(drop=True)
    df["uid"], df["uid_level"] = entity.build_uid(df)

    slices = {
        name: df[(df["day_idx"] >= lo) & (df["day_idx"] <= hi)]
        for name, (lo, hi) in config.SPLIT_DAYS.items()
    }

    # ---- A: resolution + cardinality per slice --------------------------
    res_rows = []
    for name in ["train", "val", "holdout"]:
        s = slices[name]
        lv = s["uid_level"].value_counts(normalize=True)
        per_uid = s.groupby("uid").size()
        res_rows.append(
            {
                "slice": name,
                "rows": len(s),
                "resolved_lv3": round(float(lv.get(3, 0.0)), 4),
                "d1_null_lv2": round(float(lv.get(2, 0.0)), 4),
                "addr1_null_lv1": round(float(lv.get(1, 0.0)), 4),
                "uid_cardinality": int(s["uid"].nunique()),
                "txns_per_uid_mean": round(float(per_uid.mean()), 2),
                "txns_per_uid_p50": float(per_uid.median()),
                "txns_per_uid_p90": float(per_uid.quantile(0.9)),
                "txns_per_uid_p99": float(per_uid.quantile(0.99)),
                "txns_per_uid_max": int(per_uid.max()),
                "share_singleton_uids": round(float((per_uid == 1).mean()), 4),
            }
        )
    res = pd.DataFrame(res_rows)
    print("UID RESOLUTION / CARDINALITY")
    print(res.to_string(index=False))

    # null-pattern drivers
    print("\ncomponent null rates (whole data): card1 %.4f addr1 %.4f D1 %.4f"
          % (df["card1"].isna().mean(), df["addr1"].isna().mean(),
             df["D1"].isna().mean()))
    print("addr1 null by slice:",
          {n: round(float(slices[n]["addr1"].isna().mean()), 4)
           for n in ["train", "val", "holdout"]})

    # ---- B: entity novelty ----------------------------------------------
    train = slices["train"]
    nov_rows = []
    for name in ["val", "holdout"]:
        s = slices[name]
        lo = config.SPLIT_DAYS[name][0]
        before = df[df["day_idx"] < lo]  # everything strictly before the slice
        for key in KEYS:
            seen_train = set(train[key].dropna().unique())
            seen_before = set(before[key].dropna().unique())
            v = s[key]
            nonnull = v.notna()
            nov_train = (~v[nonnull].isin(seen_train)).mean()
            nov_before = (~v[nonnull].isin(seen_before)).mean()
            nov_rows.append(
                {
                    "slice": name,
                    "key": key,
                    "null_rate": round(float((~nonnull).mean()), 4),
                    "novel_vs_train": round(float(nov_train), 4),
                    "novel_vs_all_prior": round(float(nov_before), 4),
                }
            )
    nov = pd.DataFrame(nov_rows)
    print("\nENTITY NOVELTY (share of non-null rows with unseen key)")
    print(nov.to_string(index=False))

    # how much of the fraud sits on novel entities? (train/val only — no
    # holdout labels are read anywhere in Stage 2)
    tt_y = pd.read_csv(config.RAW_TRANSACTION, usecols=["TransactionID", "isFraud"])
    val = slices["val"].merge(tt_y, on="TransactionID")
    seen_train_uid = set(train["uid"].unique())
    val_novel = ~val["uid"].isin(seen_train_uid)
    fr_novel = val.loc[val_novel, "isFraud"].mean()
    fr_seen = val.loc[~val_novel, "isFraud"].mean()
    pos_share_novel = val.loc[val_novel, "isFraud"].sum() / val["isFraud"].sum()
    print(f"\nval fraud rate on novel-vs-train UIDs: {fr_novel:.4f}; "
          f"on seen UIDs: {fr_seen:.4f}; "
          f"share of val positives on novel UIDs: {pos_share_novel:.4f}")

    out = {
        "resolution": res.to_dict("records"),
        "novelty": nov.to_dict("records"),
        "val_fraud_rate_novel_uid": float(fr_novel),
        "val_fraud_rate_seen_uid": float(fr_seen),
        "val_positive_share_on_novel_uid": float(pos_share_novel),
    }
    (OUT / "uid_novelty.json").write_text(json.dumps(out, indent=2))

    assert config.HOLDOUT_ACCESS_LOG.read_text() == ""
    print("holdout access log still empty")


if __name__ == "__main__":
    main()
