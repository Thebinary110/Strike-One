"""Contract, audit, route, and policy on hand-built frames."""

import numpy as np
import pandas as pd
import pytest

from strikeone import contract
from strikeone.audit import audit
from strikeone.policy_engine import policy
from strikeone.route import route

D = 86_400


def frame():
    # entity e1: legit d1, STRIKE d2, propagated d20 (visible to a 7d list),
    # e2: STRIKE d30; e3: legit rows only
    return pd.DataFrame({
        "txid": [1, 2, 3, 4, 5, 6],
        "when": [1 * D, 2 * D, 20 * D, 30 * D, 5 * D, 25 * D],
        "amt": [10.0, 100.0, 50.0, 200.0, 20.0, 30.0],
        "who": ["e1", "e1", "e1", "e2", "e3", "e3"],
        "bad": [0, 1, 1, 1, 0, 0],
        "s": [0.1, 0.9, 0.8, 0.7, 0.2, 0.1],
    })


def mapped():
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "score": "s"},
        label_delay_days=7.0, source="test",
    )
    return contract.apply_mapping(frame(), m), m


def test_mapping_and_sort():
    df, _ = mapped()
    assert list(df.columns) >= ["transaction_id"]
    assert df["t"].is_monotonic_increasing
    assert df["entity"].tolist()[0] == "e1"


def test_mapping_missing_required():
    m = contract.Mapping(columns={"transaction_id": "txid"}, source="x")
    with pytest.raises(contract.ContractError, match="missing required"):
        contract.apply_mapping(frame(), m)


def test_check_refuses_nonbinary_labels():
    f = frame()
    f.loc[0, "bad"] = 3
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad"},
        source="test")
    rep = contract.check(contract.apply_mapping(f, m), m)
    assert not rep.ok and any("binary" in e for e in rep.errors)


def test_check_refuses_bad_delay():
    df, m = mapped()
    m.label_delay_days = 9999
    rep = contract.check(df, m)
    assert not rep.ok and any("delay" in e for e in rep.errors)


def test_check_passes_and_counts():
    df, m = mapped()
    rep = contract.check(df, m)
    assert rep.ok
    assert rep.stats["positives"] == 3


def test_audit_hand_numbers():
    df, m = mapped()
    r = audit(df, label_delay_days=7.0)
    # episodes: e1 (strike d2), e2 (strike d30) -> 2; propagated: d20 row
    assert r.stats["episodes"] == 2
    assert r.stats["propagated_rows"] == 1
    # blocklist with 7d delay: at d20, e1's d2 fraud is 18d old -> recovered;
    # e2's d30 strike has no prior -> not recovered
    assert r.blocklist["recovered_rows"] == 1
    assert r.blocklist["first_strike_catches"] == 0
    assert r.headline["ap"] > 0.9  # scores rank frauds on top here
    assert "first attempt" in r.sentence


def test_route_lift_and_lane1():
    df, m = mapped()
    r = route(df, label_delay_days=7.0)
    # only e1's d20 row is flagged at its time
    assert r.lane1["rows"] == 1
    assert r.lane1["legit_blocked"] == 0
    assert (r.decisions["lane"] == "auto-block").sum() == 1
    assert all(c["fs_recall_on"] >= 0 for c in r.curve)


def test_route_prospective_blocklist_file():
    df, m = mapped()
    df2 = df.drop(columns=["label"])
    r = route(df2, blocklist_entities={"e3"})
    assert r.lane1["rows"] == 2  # both e3 rows


def test_policy_needs_p():
    df, _ = mapped()
    with pytest.raises(ValueError, match="calibrated probability"):
        policy(df, {})


def test_policy_clamps_and_prices():
    df, _ = mapped()
    df = df.assign(p=[0.01, 0.9, 0.8, 0.7, 0.02, 0.01])
    r = policy(df, {"m": 99, "a": -1})
    assert r.params["m"] == 0.25 and r.params["a"] == 0.05
    assert sum(r.mix["pct"]) == pytest.approx(100, abs=0.5)
    assert r.costs["policy"] <= r.costs["approve_all"]
    assert r.worst_corner is not None


def test_iso_timestamp_span_survives_pandas_units():
    # regression: pandas 3 parses ISO strings to datetime64[us]; a naive
    # int64/1e9 cast silently shrank 40 days to 0.04 days
    f = frame().assign(when=["2025-11-01T00:00:00", "2025-11-02T00:00:00",
                             "2025-11-20T00:00:00", "2025-11-30T00:00:00",
                             "2025-11-05T00:00:00", "2025-11-25T00:00:00"])
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad"},
        source="test")
    df = contract.apply_mapping(f, m)
    assert (df["t"].max() - df["t"].min()) / 86400 == pytest.approx(29.0)


def test_synthetic_example_is_deterministic():
    from strikeone.examples import synthetic
    a, b = synthetic(seed=7), synthetic(seed=7)
    assert len(a) == len(b)
    assert float(a["model_score"].sum()) == float(b["model_score"].sum())
