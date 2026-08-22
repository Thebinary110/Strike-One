"""Episode construction and friction accounting (Stage 3 definitions).

An *episode* is an entity (UID) with at least one isFraud=1 transaction. The
earliest fraud transaction (by time, TransactionID tiebreak) is the *first
strike*; every later fraud transaction on the same entity is *propagated* —
in a real system the entity is already blocklisted by then.

NORMATIVE: roles are defined on the entity's GLOBAL chronological stream,
never within an evaluation slice. An entity whose first strike lands in the
training period and which reappears flagged in validation/holdout is
PROPAGATED there — a per-slice "first fraud per UID" would misclassify it as
a fresh first strike and inflate first-strike metrics. Callers must compute
roles on the full history and then slice the result; see
tests/test_episodes.py::test_roles_are_global_across_slices.

Every intervention (alert) is classified:
  first-strike catch  alert on the entity's first fraud transaction
  redundant           alert on a later fraud transaction of the same entity
  false positive      alert on a legitimate transaction
                      (sub-split: on an already-flagged entity vs. a clean one)

friction efficiency = first-strike catches / total interventions
redundancy rate     = redundant / interventions on positives
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ROLE_LEGIT = 0
ROLE_FIRST_STRIKE = 1
ROLE_PROPAGATED = 2


def episode_roles(
    uid,
    time,
    is_fraud,
    tiebreak=None,
) -> np.ndarray:
    """Role per transaction: 0 legit, 1 first strike, 2 propagated.

    Rows must all belong to the window under analysis; if an episode began
    before the window, pass the full history and slice the result (censoring
    decisions are made by the caller, see Stage 3).
    """
    df = pd.DataFrame({"uid": uid, "t": time, "y": np.asarray(is_fraud)})
    if df["uid"].isna().any():
        raise ValueError(
            "episode_roles received null entity ids; a NaN uid would be "
            "silently treated as its own singleton entity, manufacturing "
            "spurious first strikes. Resolve or pool null keys explicitly "
            "before computing roles."
        )
    df["tb"] = tiebreak if tiebreak is not None else np.arange(len(df))
    order = df.sort_values(["uid", "t", "tb"]).index
    y_sorted = df.loc[order, "y"].to_numpy()
    uid_sorted = df.loc[order, "uid"].to_numpy()
    new_uid = np.ones(len(df), dtype=bool)
    new_uid[1:] = uid_sorted[1:] != uid_sorted[:-1]
    # cumulative fraud count per uid *before* each row
    grp = np.cumsum(new_uid) - 1
    cum = np.cumsum(y_sorted)
    base = np.zeros(len(df))
    first_of_grp = np.flatnonzero(new_uid)
    base_vals = np.concatenate([[0], cum[first_of_grp[1:] - 1]])
    base = base_vals[grp]
    prior_frauds = cum - base - y_sorted  # frauds on this uid strictly before row
    roles_sorted = np.where(
        y_sorted == 0,
        ROLE_LEGIT,
        np.where(prior_frauds == 0, ROLE_FIRST_STRIKE, ROLE_PROPAGATED),
    )
    roles = np.empty(len(df), dtype=np.int8)
    roles[order] = roles_sorted
    return roles


@dataclass(frozen=True)
class FrictionReport:
    n_alerts: int
    first_strike_catches: int
    redundant: int
    false_positives: int
    fp_on_flagged_entity: int   # FP whose entity had an earlier fraud tx
    n_episodes: int             # distinct entities with >=1 fraud in window
    friction_efficiency: float  # first-strike catches / n_alerts
    redundancy_rate: float      # redundant / alerts on positives
    first_strike_recall: float  # first-strike catches / n_episodes
    loss_weighted_fs_recall: float  # amount-weighted, first-strike tx amounts


def friction_accounting(
    roles: np.ndarray,
    alert: np.ndarray,
    amount=None,
) -> FrictionReport:
    roles = np.asarray(roles)
    alert = np.asarray(alert, dtype=bool)
    amount = np.asarray(amount, dtype=float) if amount is not None else None

    is_fs = roles == ROLE_FIRST_STRIKE
    is_prop = roles == ROLE_PROPAGATED
    is_legit = roles == ROLE_LEGIT

    fs_catch = int((alert & is_fs).sum())
    redundant = int((alert & is_prop).sum())
    fp = int((alert & is_legit).sum())
    n_alerts = int(alert.sum())
    n_episodes = int(is_fs.sum())  # one first strike per episode

    # FP on already-flagged entity requires entity context; approximated by
    # the caller passing roles computed on the full window. Here we cannot
    # know it from roles alone, so callers wanting the sub-split should use
    # fp_on_flagged_entities() below. Kept at -1 when not computed.
    alerts_on_pos = fs_catch + redundant
    fe = fs_catch / n_alerts if n_alerts else float("nan")
    rr = redundant / alerts_on_pos if alerts_on_pos else float("nan")
    fsr = fs_catch / n_episodes if n_episodes else float("nan")
    if amount is not None and is_fs.sum():
        lw = amount[alert & is_fs].sum() / amount[is_fs].sum()
    else:
        lw = float("nan")
    return FrictionReport(
        n_alerts=n_alerts,
        first_strike_catches=fs_catch,
        redundant=redundant,
        false_positives=fp,
        fp_on_flagged_entity=-1,
        n_episodes=n_episodes,
        friction_efficiency=fe,
        redundancy_rate=rr,
        first_strike_recall=fsr,
        loss_weighted_fs_recall=float(lw),
    )


def fp_on_flagged_entities(uid, time, is_fraud, roles, alert, tiebreak=None) -> int:
    """Count false-positive alerts on entities already flagged at an earlier
    timestamp (a blocklist would have intercepted these too)."""
    df = pd.DataFrame(
        {
            "uid": uid,
            "t": time,
            "y": np.asarray(is_fraud),
            "alert": np.asarray(alert, dtype=bool),
        }
    )
    df["tb"] = tiebreak if tiebreak is not None else np.arange(len(df))
    df = df.sort_values(["uid", "t", "tb"])
    prior_fraud = (
        df.groupby("uid", sort=False)["y"].cumsum() - df["y"]
    ) > 0
    return int((df["alert"] & (df["y"] == 0) & prior_fraud).sum())
