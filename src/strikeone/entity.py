"""Point-in-time entity aggregates.

Every function here answers, for a transaction at time t: "what did this
entity look like strictly before t?" — using prior rows only. Behavioural
aggregates (counts, amounts) use all prior rows; label-derived statistics
additionally require the prior row to be at least `delay` seconds old
(invariant 3: labels are not available in production until ~7 days later).

Implementation: rows are sorted by (entity, time, tiebreak); each entity's
timeline is offset onto a disjoint int64 range so a single global
searchsorted answers per-entity window queries. "Prior" means earlier in
this sort order, so same-timestamp rows are ordered deterministically by
the tiebreak (TransactionID everywhere in this project).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strikeone import config

_OFFSET = np.int64(2**31)  # > max TransactionDT (15.8M s) + max window (30 d)


def _sorted_space(key, time, tiebreak):
    """Factorize + sort; returns (order, ord_sorted, tp_sorted, null_key_mask)."""
    key = pd.Series(np.asarray(key, dtype=object))
    codes, _ = pd.factorize(key, use_na_sentinel=True)
    null_key = codes == -1
    t = np.asarray(time, dtype=np.int64)
    tb = np.asarray(tiebreak)
    order = np.lexsort((tb, t, codes))
    ords = codes[order].astype(np.int64)
    tp = ords * _OFFSET + t[order]
    return order, ords, tp, null_key


def _group_starts(ords: np.ndarray) -> np.ndarray:
    """Index of each row's group start, in sorted space."""
    new = np.ones(len(ords), dtype=bool)
    new[1:] = ords[1:] != ords[:-1]
    starts = np.flatnonzero(new)
    return starts[np.cumsum(new) - 1]


def pit_window_aggs(
    key, time, amount, tiebreak, windows_days=(1, 7, 30), prefix="ent"
) -> pd.DataFrame:
    """Prior-window count, mean amount, and velocity per window.

    For a row at time t and window w: prior rows of the same entity, earlier
    in sort order, with time >= t - w. Rows with a null key get NaN.
    """
    n = len(np.asarray(time))
    order, ords, tp, null_key = _sorted_space(key, time, tiebreak)
    amt = np.asarray(amount, dtype=np.float64)[order]
    t_sorted = np.asarray(time, dtype=np.int64)[order]
    starts = _group_starts(ords)
    prefix_amt = np.concatenate([[0.0], np.cumsum(amt)])
    pos = np.arange(len(tp))

    out = {}
    for w in windows_days:
        w_sec = np.int64(w * config.SECONDS_PER_DAY)
        q = ords * _OFFSET + (t_sorted - w_sec)
        left = np.searchsorted(tp, q, side="left")
        left = np.maximum(left, starts)  # never cross into another entity
        cnt = (pos - left).astype(np.float64)
        amt_sum = prefix_amt[pos] - prefix_amt[left]
        mean = np.where(cnt > 0, amt_sum / np.where(cnt > 0, cnt, 1), np.nan)
        cnt_out = np.full(n, np.nan)
        mean_out = np.full(n, np.nan)
        cnt_out[order] = cnt
        mean_out[order] = mean
        cnt_out[null_key] = np.nan
        mean_out[null_key] = np.nan
        out[f"{prefix}_cnt_{w}d"] = cnt_out.astype(np.float32)
        out[f"{prefix}_amt_mean_{w}d"] = mean_out.astype(np.float32)
        out[f"{prefix}_velocity_{w}d"] = (cnt_out / w).astype(np.float32)
    return pd.DataFrame(out)


def pit_expanding_stats(
    key, time, values: pd.DataFrame, tiebreak, prefix="uid", with_std=True
) -> pd.DataFrame:
    """Expanding prior-row mean (and std) of each column in `values`.

    NaN cells contribute nothing; the count of valid prior cells is tracked
    per column. mean needs >=1 valid prior cell, std needs >=2.
    """
    n = len(values)
    order, ords, _, null_key = _sorted_space(key, time, tiebreak)
    g = pd.Series(ords)

    out = {}
    for c in values.columns:
        v = values[c].to_numpy(dtype=np.float64)[order]
        valid = (~np.isnan(v)).astype(np.float64)
        s = np.nan_to_num(v)
        d = pd.DataFrame({"valid": valid, "s": s, "s2": s * s})
        cum = d.groupby(g.values).cumsum().to_numpy()
        cv = cum[:, 0] - valid
        cs = cum[:, 1] - s
        cs2 = cum[:, 2] - s * s
        mean = np.where(cv > 0, cs / np.where(cv > 0, cv, 1), np.nan)
        col_mean = np.full(n, np.nan)
        col_mean[order] = mean
        col_mean[null_key] = np.nan
        out[f"{prefix}_{c}_mean"] = col_mean.astype(np.float32)
        if with_std:
            var = np.where(
                cv > 1,
                (cs2 - cv * mean**2) / np.where(cv > 1, cv - 1, 1),
                np.nan,
            )
            std = np.sqrt(np.clip(var, 0, None))
            col_std = np.full(n, np.nan)
            col_std[order] = std
            col_std[null_key] = np.nan
            out[f"{prefix}_{c}_std"] = col_std.astype(np.float32)
    return pd.DataFrame(out)


def build_uid(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Published UID recipe: card1 + "_" + addr1 + "_" + floor(day - D1).

    `day - D1` recovers the card's first-seen day (D1 ~ days since the card
    began transacting), so the triple approximates one client. NaN
    components are stringified ('nan'), faithful to the public kernels —
    rows sharing a null pattern pool into coarser pseudo-entities.

    Returns (uid, level): level 3 = all three components present,
    level 2 = D1 null (addr1 present), level 1 = addr1 null.
    """
    first_seen = np.floor(df["day"] - df["D1"])
    uid = (
        df["card1"].astype(str)
        + "_"
        + df["addr1"].astype(str)
        + "_"
        + first_seen.astype(str)
    )
    level = np.where(
        df["addr1"].isna(), 1, np.where(df["D1"].isna(), 2, 3)
    )
    return uid, pd.Series(level, index=df.index, dtype=np.int8)


def pit_delayed_label_stats(
    key, time, y, tiebreak, delay_days=config.VERIFICATION_DELAY_DAYS, prefix="ent"
) -> pd.DataFrame:
    """Prior fraud statistics using only labels already available at t.

    A prior transaction's label counts only if it is at least `delay_days`
    old at time t (time <= t - delay). Returns the labeled-prior count and
    the fraud rate among them (NaN when no labeled prior rows exist).
    """
    n = len(np.asarray(time))
    order, ords, tp, null_key = _sorted_space(key, time, tiebreak)
    t_sorted = np.asarray(time, dtype=np.int64)[order]
    y_sorted = np.asarray(y, dtype=np.float64)[order]
    starts = _group_starts(ords)
    prefix_y = np.concatenate([[0.0], np.cumsum(y_sorted)])

    delay = np.int64(delay_days * config.SECONDS_PER_DAY)
    q = ords * _OFFSET + (t_sorted - delay)
    right = np.searchsorted(tp, q, side="right")
    right = np.maximum(right, starts)
    cnt = (right - starts).astype(np.float64)
    frauds = prefix_y[right] - prefix_y[starts]
    rate = np.where(cnt > 0, frauds / np.where(cnt > 0, cnt, 1), np.nan)

    cnt_out = np.full(n, np.nan)
    rate_out = np.full(n, np.nan)
    cnt_out[order] = cnt
    rate_out[order] = rate
    cnt_out[null_key] = np.nan
    rate_out[null_key] = np.nan
    return pd.DataFrame(
        {
            f"{prefix}_labeled_cnt": cnt_out.astype(np.float32),
            f"{prefix}_fraud_rate": rate_out.astype(np.float32),
        }
    )
