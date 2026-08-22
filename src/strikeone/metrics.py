"""Evaluation metrics.

Everything here operates on in-memory arrays; nothing reads the holdout
(that is strikeone.seal's job). Episode-level metrics live in
strikeone.episodes and are re-exported here.

Cost model (Stage 4 of the brief). Realized per-transaction cost, given the
true label, amount A, and parameters m (contribution margin), a (step-up
abandonment rate), e (step-up efficacy), c_h (chargeback handling cost):

    action    fraud (y=1)          legit (y=0)
    approve   A + c_h              0
    step-up   (1-e) * (A + c_h)    a * m * A
    block     0                    m * A

Expected cost under calibrated probability p is the y-expectation of the
same table; the decision engine (Stage 4) takes the argmin.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)

from strikeone.episodes import (  # noqa: F401  (re-exported)
    FrictionReport,
    episode_roles,
    friction_accounting,
)

APPROVE, STEPUP, BLOCK = 0, 1, 2
ACTION_NAMES = {APPROVE: "approve", STEPUP: "step-up", BLOCK: "block"}


# ---------------------------------------------------------------- headline

def average_precision(y_true, y_score) -> float:
    return float(average_precision_score(y_true, y_score))


def roc_auc(y_true, y_score) -> float:
    return float(roc_auc_score(y_true, y_score))


def pr_curve(y_true, y_score):
    precision, recall, thresholds = precision_recall_curve(y_true, y_score)
    return precision, recall, thresholds


def alerts_at_budget(y_score, budget: int) -> np.ndarray:
    """Boolean alert mask for the top-`budget` scores (ties broken by order)."""
    y_score = np.asarray(y_score)
    if budget <= 0:
        return np.zeros(len(y_score), dtype=bool)
    idx = np.argsort(-y_score, kind="stable")[:budget]
    mask = np.zeros(len(y_score), dtype=bool)
    mask[idx] = True
    return mask


# ------------------------------------------------------- card precision@k

def card_precision_at_k(day_idx, card_id, y_true, y_score, k: int) -> float:
    """Daily Card Precision@k (Fraud Detection Handbook convention).

    Per day: rank cards by their max score that day, take the top
    min(k, #cards) cards, precision = share of those cards with >=1 fraud
    transaction that day. Return the mean over days.
    """
    df = pd.DataFrame(
        {"day": day_idx, "card": card_id, "y": y_true, "s": y_score}
    )
    per_card = (
        df.groupby(["day", "card"], sort=False)
        .agg(max_score=("s", "max"), any_fraud=("y", "max"))
        .reset_index()
    )
    precisions = []
    for _, g in per_card.groupby("day", sort=False):
        top = g.nlargest(min(k, len(g)), "max_score")
        precisions.append(top["any_fraud"].mean())
    return float(np.mean(precisions))


DEFAULT_CPK_GRID = (10, 25, 50, 100)


def card_precision_curve(day_idx, card_id, y_true, y_score, ks=DEFAULT_CPK_GRID):
    """Card Precision@k over a grid of k, as {k: precision}.

    Reported as a curve because at ~100 positives/day a large single k makes
    precision@k and recall@k nearly the same number — a degenerate point.
    """
    return {
        int(k): card_precision_at_k(day_idx, card_id, y_true, y_score, k)
        for k in ks
    }


# ------------------------------------------------------------------ cost

@dataclass(frozen=True)
class CostParams:
    m: float      # contribution margin lost on a rejected good order
    a: float      # step-up abandonment rate
    e: float      # step-up efficacy against a fraud attempt
    c_h: float    # chargeback handling cost (same currency unit as amounts)


def realized_cost(y_true, action, amount, p: CostParams) -> np.ndarray:
    """Per-transaction realized cost given true labels (for evaluation)."""
    y = np.asarray(y_true, dtype=float)
    act = np.asarray(action)
    A = np.asarray(amount, dtype=float)
    cost = np.empty_like(A)
    is_ap, is_su, is_bl = act == APPROVE, act == STEPUP, act == BLOCK
    if not np.all(is_ap | is_su | is_bl):
        raise ValueError("unknown action code")
    cost[is_ap] = y[is_ap] * (A[is_ap] + p.c_h)
    cost[is_su] = (
        y[is_su] * (1 - p.e) * (A[is_su] + p.c_h)
        + (1 - y[is_su]) * p.a * p.m * A[is_su]
    )
    cost[is_bl] = (1 - y[is_bl]) * p.m * A[is_bl]
    return cost


def expected_cost_matrix(p_fraud, amount, p: CostParams) -> np.ndarray:
    """(n, 3) expected cost per action, for the Stage 4 argmin policy."""
    pf = np.asarray(p_fraud, dtype=float)
    A = np.asarray(amount, dtype=float)
    approve = pf * (A + p.c_h)
    stepup = pf * (1 - p.e) * (A + p.c_h) + (1 - pf) * p.a * p.m * A
    block = (1 - pf) * p.m * A
    return np.stack([approve, stepup, block], axis=1)


def savings(y_true, action, amount, p: CostParams) -> float:
    """(Cost_baseline - Cost_policy) / Cost_baseline.

    Baseline = the cheaper of approve-all and block-all on the same rows.
    """
    n = len(np.asarray(amount))
    policy = realized_cost(y_true, action, amount, p).sum()
    approve_all = realized_cost(y_true, np.full(n, APPROVE), amount, p).sum()
    block_all = realized_cost(y_true, np.full(n, BLOCK), amount, p).sum()
    baseline = min(approve_all, block_all)
    if baseline == 0:
        raise ValueError("baseline cost is zero; savings undefined")
    return float((baseline - policy) / baseline)


# ------------------------------------------------------------- bootstrap

def bootstrap_ci(
    stat_fn,
    n_rows: int,
    n_boot: int = 1000,
    seed: int = 0,
    groups=None,
    alpha: float = 0.05,
):
    """Percentile bootstrap.

    stat_fn: callable(idx: np.ndarray) -> float, evaluated on resampled row
    indices. If `groups` is given (array of group labels per row, e.g. entity
    ids), whole groups are resampled — required for episode metrics, where
    rows within an entity are not exchangeable.

    Returns (point, lo, hi). Resamples where stat_fn returns NaN (e.g. no
    positives drawn) are dropped.
    """
    rng = np.random.default_rng(seed)
    point = float(stat_fn(np.arange(n_rows)))
    stats = []
    if groups is not None:
        groups = np.asarray(groups)
        uniq = pd.unique(groups)
        rows_by_group = pd.Series(np.arange(n_rows)).groupby(groups).apply(np.asarray)
    for _ in range(n_boot):
        if groups is None:
            idx = rng.integers(0, n_rows, n_rows)
        else:
            picked = rng.integers(0, len(uniq), len(uniq))
            idx = np.concatenate(rows_by_group.iloc[picked].to_list())
        v = stat_fn(idx)
        if not np.isnan(v):
            stats.append(v)
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return point, float(lo), float(hi)


def paired_bootstrap_diff(
    stat_fn_a,
    stat_fn_b,
    n_rows: int,
    n_boot: int = 1000,
    seed: int = 0,
    groups=None,
    alpha: float = 0.05,
):
    """Paired bootstrap for stat(B) - stat(A) on the same resampled rows.

    Returns (delta, lo, hi, p_leq_zero) where p_leq_zero is the share of
    resamples with delta <= 0 (a one-sided evidence measure for B > A).
    """
    rng = np.random.default_rng(seed)
    delta_point = float(stat_fn_b(np.arange(n_rows)) - stat_fn_a(np.arange(n_rows)))
    if groups is not None:
        groups = np.asarray(groups)
        uniq = pd.unique(groups)
        rows_by_group = pd.Series(np.arange(n_rows)).groupby(groups).apply(np.asarray)
    deltas = []
    for _ in range(n_boot):
        if groups is None:
            idx = rng.integers(0, n_rows, n_rows)
        else:
            picked = rng.integers(0, len(uniq), len(uniq))
            idx = np.concatenate(rows_by_group.iloc[picked].to_list())
        va, vb = stat_fn_a(idx), stat_fn_b(idx)
        if not (np.isnan(va) or np.isnan(vb)):
            deltas.append(vb - va)
    deltas = np.asarray(deltas)
    lo, hi = np.percentile(deltas, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    p_leq_zero = float((deltas <= 0).mean())
    return delta_point, float(lo), float(hi), p_leq_zero
