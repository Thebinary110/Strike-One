"""Ingestion: load the two raw IEEE-CIS training files, verify, join, add day index.

The official test set is never touched (its labels were never released).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strikeone import config


class DataVerificationError(RuntimeError):
    pass


def load_raw(verify: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load train_transaction.csv and train_identity.csv, verifying shapes."""
    tt = pd.read_csv(config.RAW_TRANSACTION)
    ti = pd.read_csv(config.RAW_IDENTITY)
    if verify:
        if tt.shape != config.EXPECTED_TRANSACTION_SHAPE:
            raise DataVerificationError(
                f"train_transaction shape {tt.shape} != expected "
                f"{config.EXPECTED_TRANSACTION_SHAPE}; the download is wrong."
            )
        if ti.shape != config.EXPECTED_IDENTITY_SHAPE:
            raise DataVerificationError(
                f"train_identity shape {ti.shape} != expected "
                f"{config.EXPECTED_IDENTITY_SHAPE}; the download is wrong."
            )
        if not tt["TransactionID"].is_unique or not ti["TransactionID"].is_unique:
            raise DataVerificationError("TransactionID is not unique.")
        if not ti["TransactionID"].isin(tt["TransactionID"]).all():
            raise DataVerificationError(
                "identity rows exist with no matching transaction row."
            )
    return tt, ti


def build_joined(tt: pd.DataFrame, ti: pd.DataFrame) -> pd.DataFrame:
    """Left-join identity onto transactions and add day columns.

    day    : float days since the (unknown) reference point of TransactionDT
    day_idx: integer day bucket, floor(day); used for split membership
    """
    df = tt.merge(ti, on="TransactionID", how="left")
    day = df["TransactionDT"] / config.SECONDS_PER_DAY
    df = pd.concat(
        [df, day.rename("day"), np.floor(day).astype(np.int32).rename("day_idx")],
        axis=1,
    )
    # Chronological order everywhere downstream; TransactionID breaks DT ties.
    df = df.sort_values(["TransactionDT", "TransactionID"]).reset_index(drop=True)
    # Downcast float64 -> float32: halves memory, no modeling impact.
    f64 = df.select_dtypes(include="float64").columns
    df[f64] = df[f64].astype(np.float32)
    return df


def slice_days(df: pd.DataFrame, slice_name: str) -> pd.DataFrame:
    lo, hi = config.SPLIT_DAYS[slice_name]
    return df[(df["day_idx"] >= lo) & (df["day_idx"] <= hi)]
