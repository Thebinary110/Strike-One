"""Central constants: paths, split boundaries, seeds.

All time handling is in *day indices* derived from TransactionDT (a seconds
offset from an unknown reference point). We never convert to calendar dates.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
REPORTS = REPO_ROOT / "reports"

RAW_TRANSACTION = DATA_RAW / "train_transaction.csv"
RAW_IDENTITY = DATA_RAW / "train_identity.csv"

MODELING_PARQUET = DATA_PROCESSED / "modeling.parquet"   # days 1-150
HOLDOUT_PARQUET = DATA_PROCESSED / "holdout.parquet"     # days 151-182, sealed
HOLDOUT_SHA_FILE = REPO_ROOT / "data" / "holdout.sha256"  # committed
HOLDOUT_ACCESS_LOG = REPORTS / "holdout_access.log"       # committed

# Expected raw fingerprints; a mismatch means the download is wrong.
# Shapes alone would pass a subtly different mirror; the exact positive
# count and max TransactionDT would not.
EXPECTED_TRANSACTION_SHAPE = (590_540, 394)
EXPECTED_IDENTITY_SHAPE = (144_233, 41)
EXPECTED_POSITIVES = 20_663
EXPECTED_MAX_TRANSACTION_DT = 15_811_131

SECONDS_PER_DAY = 86_400

# Chronological split, inclusive integer-day bounds (day = floor(DT/86400)).
# Day range in the data is 1..182.
SPLIT_DAYS = {
    "train": (1, 112),       # fitting
    "delay_gap": (113, 119),  # matches the 7-day label-availability delay
    "val": (120, 147),        # tuning, calibration, threshold derivation
    "blind_gap": (148, 150),  # stops timedelta features bridging the boundary
    "holdout": (151, 182),    # opened once, at Stage 7
}

# Label-derived features must be lagged by this many days (labels are not
# available in production until roughly this long after the transaction).
VERIFICATION_DELAY_DAYS = 7

SEED = 20260822
