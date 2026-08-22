"""Hand-computed examples for the point-in-time entity machinery."""

import numpy as np
import pandas as pd
import pytest

from strikeone import entity as E

D = 86_400  # seconds per day


def test_window_aggs_hand():
    key = ["a", "a", "a", "b"]
    t = [0, 2 * D, 3 * D, 0]
    amt = [10.0, 20.0, 30.0, 40.0]
    tb = [1, 2, 3, 4]
    f = E.pit_window_aggs(key, t, amt, tb, windows_days=(1, 7))
    # 7d window: row0 -> 0 prior; row1 (t=2d) -> row0 (t=0 >= -5d): cnt 1, mean 10
    #            row2 (t=3d) -> rows 0,1: cnt 2, mean 15 ; row3 (b) -> 0 prior
    assert f["ent_cnt_7d"].tolist() == [0, 1, 2, 0]
    assert np.isnan(f["ent_amt_mean_7d"][0])
    assert f["ent_amt_mean_7d"][1] == pytest.approx(10.0)
    assert f["ent_amt_mean_7d"][2] == pytest.approx(15.0)
    # 1d window: row1 (t=2d, cutoff 1d) -> row0 at t=0 excluded: cnt 0
    #            row2 (t=3d, cutoff 2d) -> row1 at t=2d included: cnt 1, mean 20
    assert f["ent_cnt_1d"].tolist() == [0, 0, 1, 0]
    assert f["ent_amt_mean_1d"][2] == pytest.approx(20.0)
    assert f["ent_velocity_7d"][2] == pytest.approx(2 / 7)


def test_window_aggs_ties_and_nulls():
    # same key, same timestamp: tiebreak order decides "prior"
    f = E.pit_window_aggs(["a", "a"], [D, D], [5.0, 7.0], [2, 1], windows_days=(7,))
    # row with tb=1 is first: 0 prior; row with tb=2 sees it
    assert f["ent_cnt_7d"].tolist() == [1, 0]
    assert f["ent_amt_mean_7d"][0] == pytest.approx(7.0)
    # null key -> NaN features
    f2 = E.pit_window_aggs([None, None], [0, D], [1.0, 2.0], [1, 2], windows_days=(7,))
    assert np.isnan(f2["ent_cnt_7d"]).all()


def test_expanding_stats_hand():
    vals = pd.DataFrame({"x": [1.0, 2.0, 4.0]})
    f = E.pit_expanding_stats(["a"] * 3, [0, D, 2 * D], vals, [1, 2, 3])
    assert np.isnan(f["uid_x_mean"][0])
    assert f["uid_x_mean"][1] == pytest.approx(1.0)
    assert f["uid_x_mean"][2] == pytest.approx(1.5)
    assert np.isnan(f["uid_x_std"][1])  # one prior value: std undefined
    assert f["uid_x_std"][2] == pytest.approx(np.std([1, 2], ddof=1))


def test_expanding_stats_nan_cells():
    vals = pd.DataFrame({"x": [1.0, np.nan, 3.0]})
    f = E.pit_expanding_stats(["a"] * 3, [0, D, 2 * D], vals, [1, 2, 3])
    # row2's priors: rows 0 (valid) and 1 (NaN, contributes nothing)
    assert f["uid_x_mean"][2] == pytest.approx(1.0)
    assert np.isnan(f["uid_x_std"][2])


def test_delayed_label_stats_hand():
    key = ["a"] * 3
    t = [0, 8 * D, 20 * D]
    y = [1, 0, 1]
    f = E.pit_delayed_label_stats(key, t, y, [1, 2, 3], delay_days=7)
    # row0: nothing labeled yet -> cnt 0, rate NaN
    # row1 (t=8d): labels available for rows with t <= 1d -> row0: rate 1.0
    # row2 (t=20d): rows with t <= 13d -> rows 0,1: rate 0.5
    assert f["ent_labeled_cnt"].tolist() == [0, 1, 2]
    assert np.isnan(f["ent_fraud_rate"][0])
    assert f["ent_fraud_rate"][1] == pytest.approx(1.0)
    assert f["ent_fraud_rate"][2] == pytest.approx(0.5)


def test_delayed_label_excludes_recent():
    # a fraud 3 days ago is NOT yet visible under a 7-day delay
    f = E.pit_delayed_label_stats(["a", "a"], [0, 3 * D], [1, 0], [1, 2], delay_days=7)
    assert f["ent_labeled_cnt"].tolist() == [0, 0]
    assert np.isnan(f["ent_fraud_rate"][1])


def test_no_cross_entity_bleed():
    # entity b's rows must not see entity a's history
    key = ["a", "b"]
    f = E.pit_window_aggs(key, [0, D], [100.0, 1.0], [1, 2], windows_days=(30,))
    assert f["ent_cnt_30d"].tolist() == [0, 0]
    g = E.pit_delayed_label_stats(key, [0, 20 * D], [1, 0], [1, 2], delay_days=7)
    assert g["ent_labeled_cnt"].tolist() == [0, 0]
