"""Baseline feature construction and hygiene.

Permanent exclusions, each with its reason, live in PERMANENT_EXCLUSIONS.
Categorical encodings are fitted on the training slice only; category values
unseen in training map to missing (never to a fresh code) — the encoder
learns nothing from evaluation-period data.

High-cardinality numeric identifiers (card1/card2/card3/card5, addr1/addr2)
are left numeric: LightGBM's native categorical handling on 10k+ categories
overfits small leaves, and the numeric treatment is the common published
baseline. Documented as a judgment call in PROPOSALS.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strikeone import config

PERMANENT_EXCLUSIONS = {
    "isFraud": "label",
    "TransactionID": (
        "monotonic in TransactionDT (verified in Stage 0) — a pure time "
        "proxy; splits on it memorise the period, not the behaviour"
    ),
    "TransactionDT": "raw monotonic time offset — cannot generalise forward",
    "day": "float day index — monotonic time proxy",
    "day_idx": "integer day index — monotonic time proxy / split key",
}


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclical time-of-day / day-of-week. Phase of `dow` is arbitrary
    (TransactionDT's reference point is unknown); only its periodicity is
    meaningful, which is all a within-week pattern needs."""
    dt = df["TransactionDT"]
    hour = (dt % config.SECONDS_PER_DAY) / 3600.0
    dow = (dt // config.SECONDS_PER_DAY) % 7
    out = pd.DataFrame(
        {
            "hour": hour.astype(np.float32),
            "dow": dow.astype(np.float32),
            "hour_sin": np.sin(2 * np.pi * hour / 24).astype(np.float32),
            "hour_cos": np.cos(2 * np.pi * hour / 24).astype(np.float32),
            "dow_sin": np.sin(2 * np.pi * dow / 7).astype(np.float32),
            "dow_cos": np.cos(2 * np.pi * dow / 7).astype(np.float32),
        },
        index=df.index,
    )
    return pd.concat([df, out], axis=1)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in PERMANENT_EXCLUSIONS]


def categorical_columns(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Non-numeric feature columns (strings) — LightGBM-native categoricals."""
    return [c for c in cols if not pd.api.types.is_numeric_dtype(df[c])]


def fit_categories(train_df: pd.DataFrame, cat_cols: list[str]) -> dict:
    return {c: pd.CategoricalDtype(train_df[c].dropna().unique()) for c in cat_cols}


def apply_categories(df: pd.DataFrame, dtypes: dict) -> pd.DataFrame:
    """Cast to train-fitted categories; unseen values become NaN (missing)."""
    out = df.copy()
    for c, dt in dtypes.items():
        out[c] = out[c].astype(dt)
    return out


def build_matrices(
    train_df: pd.DataFrame, eval_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[str]]:
    """(X_train, X_eval, feature_names, categorical_names)."""
    train_df = add_time_features(train_df)
    eval_df = add_time_features(eval_df)
    cols = feature_columns(train_df)
    cats = categorical_columns(train_df, cols)
    dtypes = fit_categories(train_df, cats)
    X_tr = apply_categories(train_df[cols], dtypes)
    X_ev = apply_categories(eval_df[cols], dtypes)
    return X_tr, X_ev, cols, cats
