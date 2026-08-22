"""Every metric checked against a hand-computed tiny example."""

import numpy as np
import pytest

from strikeone import metrics as M


def test_average_precision_hand():
    # ranking desc: 0.8(pos) p=1 @ r=.5 ; 0.4(neg) ; 0.35(pos) p=2/3 @ r=1
    y = [0, 0, 1, 1]
    s = [0.1, 0.4, 0.35, 0.8]
    assert M.average_precision(y, s) == pytest.approx(0.5 * 1 + 0.5 * (2 / 3))


def test_roc_auc_hand():
    # concordant pos/neg pairs: (.8,.1)+, (.8,.4)+, (.35,.1)+, (.35,.4)- => 3/4
    y = [0, 0, 1, 1]
    s = [0.1, 0.4, 0.35, 0.8]
    assert M.roc_auc(y, s) == pytest.approx(0.75)


def test_pr_curve_endpoints():
    y = [0, 1]
    s = [0.1, 0.9]
    precision, recall, _ = M.pr_curve(y, s)
    assert recall[0] == 1.0 and precision[-1] == 1.0


def test_alerts_at_budget():
    mask = M.alerts_at_budget([0.1, 0.9, 0.5], budget=2)
    assert mask.tolist() == [False, True, True]
    assert M.alerts_at_budget([0.1, 0.9], budget=0).sum() == 0


def test_card_precision_at_k_hand():
    day = [1, 1, 1, 1, 2, 2]
    card = ["A", "A", "B", "C", "D", "E"]
    y = [0, 1, 0, 0, 1, 0]
    s = [0.9, 0.2, 0.8, 0.1, 0.7, 0.6]
    # day1 top-2 cards by max score: A(fraud), B(clean) -> 0.5
    # day2 has only 2 cards: D(fraud), E(clean) -> 0.5
    assert M.card_precision_at_k(day, card, y, s, k=2) == pytest.approx(0.5)
    # k=1: day1 -> A fraud (1.0); day2 -> D fraud (1.0)
    assert M.card_precision_at_k(day, card, y, s, k=1) == pytest.approx(1.0)


def test_card_precision_curve_hand():
    day = [1, 1, 1, 1, 2, 2]
    card = ["A", "A", "B", "C", "D", "E"]
    y = [0, 1, 0, 0, 1, 0]
    s = [0.9, 0.2, 0.8, 0.1, 0.7, 0.6]
    curve = M.card_precision_curve(day, card, y, s, ks=[1, 2])
    assert curve == {1: pytest.approx(1.0), 2: pytest.approx(0.5)}


PARAMS = M.CostParams(m=0.1, a=0.2, e=0.8, c_h=15.0)


def test_realized_cost_hand():
    y = [1, 0, 1, 0, 1, 0]
    act = [M.APPROVE, M.APPROVE, M.STEPUP, M.STEPUP, M.BLOCK, M.BLOCK]
    A = [100, 100, 100, 50, 100, 50]
    cost = M.realized_cost(y, act, A, PARAMS)
    # approve+fraud: 100+15 ; approve+legit: 0
    # stepup+fraud: .2*(115)=23 ; stepup+legit: .2*.1*50=1
    # block+fraud: 0 ; block+legit: .1*50=5
    assert cost.tolist() == pytest.approx([115.0, 0.0, 23.0, 1.0, 0.0, 5.0])


def test_expected_cost_matrix_hand():
    ec = M.expected_cost_matrix([0.5], [100], PARAMS)
    # approve: .5*115 ; stepup: .5*.2*115 + .5*.2*.1*100 ; block: .5*.1*100
    assert ec[0].tolist() == pytest.approx([57.5, 11.5 + 1.0, 5.0])


def test_savings_hand():
    y, A = [1, 0], [100, 50]
    # approve-all = 115 ; block-all = 5 -> baseline 5
    perfect = [M.BLOCK, M.APPROVE]  # cost 0 -> savings 1
    assert M.savings(y, perfect, A, PARAMS) == pytest.approx(1.0)
    inverted = [M.APPROVE, M.BLOCK]  # cost 120 -> (5-120)/5 = -23
    assert M.savings(y, inverted, A, PARAMS) == pytest.approx(-23.0)


def test_bootstrap_ci_mean():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    point, lo, hi = M.bootstrap_ci(
        lambda idx: x[idx].mean(), n_rows=4, n_boot=500, seed=1
    )
    assert point == pytest.approx(2.5)
    assert lo <= point <= hi
    # determinism
    again = M.bootstrap_ci(lambda idx: x[idx].mean(), n_rows=4, n_boot=500, seed=1)
    assert (point, lo, hi) == again


def test_bootstrap_ci_grouped():
    x = np.array([1.0, 1.0, 5.0, 5.0])
    groups = ["a", "a", "b", "b"]
    point, lo, hi = M.bootstrap_ci(
        lambda idx: x[idx].mean(), n_rows=4, n_boot=200, seed=2, groups=groups
    )
    assert point == pytest.approx(3.0)
    # group bootstrap can only produce means in {1, 3, 5}
    assert lo in (1.0, 3.0) and hi in (3.0, 5.0)


def test_paired_bootstrap_diff():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    a = lambda idx: x[idx].mean()
    b = lambda idx: x[idx].mean() + 1.0
    delta, lo, hi, p = M.paired_bootstrap_diff(a, b, n_rows=4, n_boot=200, seed=3)
    assert delta == pytest.approx(1.0)
    assert lo == pytest.approx(1.0) and hi == pytest.approx(1.0)
    assert p == 0.0
