import numpy as np
import pytest

from strikeone import episodes as E


def small_case():
    uid = ["u1", "u1", "u1", "u2", "u2", "u3"]
    t = [1, 2, 3, 1, 2, 5]
    y = [0, 1, 1, 0, 1, 0]
    return uid, t, y


def test_episode_roles_hand():
    uid, t, y = small_case()
    roles = E.episode_roles(uid, t, y)
    assert roles.tolist() == [
        E.ROLE_LEGIT,
        E.ROLE_FIRST_STRIKE,
        E.ROLE_PROPAGATED,
        E.ROLE_LEGIT,
        E.ROLE_FIRST_STRIKE,
        E.ROLE_LEGIT,
    ]


def test_episode_roles_unsorted_input():
    # same case, rows shuffled — roles must land on the right rows
    uid = ["u1", "u2", "u1", "u3", "u1", "u2"]
    t = [3, 2, 1, 5, 2, 1]
    y = [1, 1, 0, 0, 1, 0]
    roles = E.episode_roles(uid, t, y)
    assert roles.tolist() == [
        E.ROLE_PROPAGATED,     # u1 t=3
        E.ROLE_FIRST_STRIKE,   # u2 t=2
        E.ROLE_LEGIT,          # u1 t=1
        E.ROLE_LEGIT,          # u3
        E.ROLE_FIRST_STRIKE,   # u1 t=2
        E.ROLE_LEGIT,          # u2 t=1
    ]


def test_tiebreak_deterministic():
    # two frauds at the same timestamp: tiebreak decides the first strike
    roles = E.episode_roles(["u", "u"], [1, 1], [1, 1], tiebreak=[2, 1])
    assert roles.tolist() == [E.ROLE_PROPAGATED, E.ROLE_FIRST_STRIKE]


def test_friction_accounting_hand():
    uid, t, y = small_case()
    roles = E.episode_roles(uid, t, y)
    alert = np.array([True, True, True, False, True, False])
    amount = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    r = E.friction_accounting(roles, alert, amount)
    assert r.n_alerts == 4
    assert r.first_strike_catches == 2   # rows 1 and 4
    assert r.redundant == 1              # row 2
    assert r.false_positives == 1        # row 0
    assert r.n_episodes == 2
    assert r.friction_efficiency == pytest.approx(2 / 4)
    assert r.redundancy_rate == pytest.approx(1 / 3)
    assert r.first_strike_recall == pytest.approx(1.0)
    assert r.loss_weighted_fs_recall == pytest.approx((20 + 50) / (20 + 50))


def test_loss_weighted_partial():
    uid = ["u1", "u2"]
    roles = E.episode_roles(uid, [1, 1], [1, 1])
    alert = np.array([True, False])
    amount = np.array([100.0, 300.0])
    r = E.friction_accounting(roles, alert, amount)
    assert r.first_strike_recall == pytest.approx(0.5)
    assert r.loss_weighted_fs_recall == pytest.approx(100 / 400)


def test_fp_on_flagged_entities():
    uid = ["u1", "u1", "u1"]
    t = [1, 2, 3]
    y = [0, 1, 0]
    alert = [True, False, True]
    roles = E.episode_roles(uid, t, y)
    assert E.fp_on_flagged_entities(uid, t, y, roles, alert) == 1
