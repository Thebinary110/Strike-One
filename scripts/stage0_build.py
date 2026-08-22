"""Stage 0: ingest, verify, join, split chronologically, seal the holdout.

Outputs:
  data/processed/modeling.parquet   days 1-150 (train + delay gap + val + blind gap)
  data/processed/holdout.parquet    days 151-182, sealed (sha256 committed)
  data/holdout.sha256               committed hash of the sealed file
  reports/holdout_access.log        committed, empty until Stage 7
  prints slice counts for reports/STAGE_0.md
"""

from __future__ import annotations

import hashlib

import pandas as pd

from strikeone import config, data, seal


def main() -> None:
    print("loading raw files ...")
    tt, ti = data.load_raw(verify=True)
    print(f"  train_transaction {tt.shape}, train_identity {ti.shape}  OK")

    df = data.build_joined(tt, ti)
    print(f"joined: {df.shape}, day_idx {df['day_idx'].min()}..{df['day_idx'].max()}")

    # ---- slice table --------------------------------------------------
    rows = []
    for name, (lo, hi) in config.SPLIT_DAYS.items():
        s = data.slice_days(df, name)
        rows.append(
            {
                "slice": name,
                "days": f"{lo}-{hi}",
                "n_days": hi - lo + 1,
                "rows": len(s),
                "positives": int(s["isFraud"].sum()),
                "fraud_rate": round(float(s["isFraud"].mean()), 5),
                "amount_sum": round(float(s["TransactionAmt"].sum()), 0),
            }
        )
    table = pd.DataFrame(rows)
    total = table[["rows", "positives"]].sum()
    print(table.to_string(index=False))
    print(f"total rows {total['rows']} (expect 590540), positives {total['positives']}")
    assert total["rows"] == 590_540, "slices do not cover the dataset"

    # ---- write modeling file (days 1-150) and seal holdout -------------
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    modeling = df[df["day_idx"] <= config.SPLIT_DAYS["blind_gap"][1]]
    holdout = data.slice_days(df, "holdout")
    modeling.to_parquet(config.MODELING_PARQUET, index=False)
    print(f"modeling.parquet: {len(modeling)} rows")

    digest = seal.seal_holdout(holdout)
    print(f"holdout.parquet: {len(holdout)} rows, sealed sha256={digest}")
    print(seal.status())

    # raw-file checksums for reproducibility
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    checks = config.REPO_ROOT / "data" / "raw_checksums.sha256"
    checks.write_text(
        f"{sha(config.RAW_TRANSACTION)}  train_transaction.csv\n"
        f"{sha(config.RAW_IDENTITY)}  train_identity.csv\n"
    )
    print(f"raw checksums written to {checks}")


if __name__ == "__main__":
    main()
