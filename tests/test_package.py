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
    assert "first labelled transaction" in r.sentence


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


def test_blocklist_comparison_is_budget_matched():
    # regression: a precision comparison at unmatched alert counts shipped
    # twice (Stage 4, then the audit output). Any comparison the output
    # renders must be computed at the blocklist's own N.
    df, _ = mapped()
    r = audit(df, label_delay_days=7.0)
    n = r.blocklist["comparison_n"]
    assert n == r.blocklist["flagged_rows"] == 1
    # independent recomputation of the scorer at exactly N alerts:
    # top-1 by score is the 0.9 row (a fraud) -> precision 1.0, and it is
    # e1's first strike -> 1 first-attempt stop
    assert r.blocklist["scorer_precision_same_n"] == pytest.approx(1.0)
    assert r.blocklist["scorer_fs_catches_same_n"] == 1


def test_next_action_derives_from_coverable_column():
    # regression: 'reviews freed/day' once used a different computation
    # than the blocklist-coverable column and contradicted it on screen
    df, _ = mapped()
    r = audit(df, label_delay_days=7.0)
    pr = next(x for x in r.budgets if x["primary"])
    coverable_per_day = pr["blocklist_coverable"] / max(r.stats["days"], 1)
    text = r.to_text()
    if coverable_per_day >= 0.5:
        assert f"about {coverable_per_day:.0f} of your" in text
    # and the budget rows always reconcile internally
    for row in r.budgets:
        assert row["hits"] + row["false_positives"] == row["budget"]
        assert row["fs_catches"] <= row["hits"]
        assert row["blocklist_coverable"] <= row["hits"]


def test_history_reclassifies_prewindow_cases():
    # window truncation: e2's d30 strike is a fresh case unless history
    # says e2 was flagged before the window; then it is already-begun,
    # excluded from first-attempt counts, and blocklist-recoverable
    df, _ = mapped()
    r0 = audit(df, label_delay_days=7.0)
    r1 = audit(df, label_delay_days=7.0, history_entities={"e2"})
    assert r0.stats["episodes"] == 2
    assert r1.stats["episodes"] == 1
    assert r1.stats["cases_reclassified"] == 1
    assert r1.blocklist["recovered_rows"] == r0.blocklist["recovered_rows"] + 1
    assert "plus your supplied history" in r1.to_text()
    assert "upper bound" in r0.to_text()


def test_liability_shift_default_preserves_frozen_policy():
    # s defaults to 0: expected costs, realized costs, and the frozen
    # config (which predates s and omits it) are bit-identical to before
    import json
    import numpy as np
    from strikeone import metrics as M

    rng = np.random.default_rng(3)
    p_, A_ = rng.random(500), rng.gamma(2, 60, 500)
    old_stepup = p_ * (1 - 0.775) * (A_ + 30.0) + (1 - p_) * 0.125 * 0.15 * A_
    prm0 = M.CostParams(m=0.15, a=0.125, e=0.775, c_h=30.0)  # s omitted
    assert prm0.s == 0.0
    ec = M.expected_cost_matrix(p_, A_, prm0)
    assert np.allclose(ec[:, 1], old_stepup)
    # the frozen Stage 4 config (no 's' key) must still construct cleanly
    frozen = {"m": 0.15, "a": 0.125, "e": 0.775, "c_h": 30.0}
    assert M.CostParams(**frozen).s == 0.0
    # and s > 0 strictly cheapens step-up on frauds, nothing else
    prm1 = M.CostParams(m=0.15, a=0.125, e=0.775, c_h=30.0, s=1.0)
    ec1 = M.expected_cost_matrix(p_, A_, prm1)
    assert np.all(ec1[:, 1] <= ec[:, 1])
    assert np.allclose(ec1[:, 0], ec[:, 0]) and np.allclose(ec1[:, 2], ec[:, 2])


def test_policy_s_dimension_clamped_and_swept():
    df, _ = mapped()
    df = df.assign(p=[0.01, 0.9, 0.8, 0.7, 0.02, 0.01])
    r = policy(df, {"s": 5})
    assert r.params["s"] == 1.0            # clamped to the declared range
    assert any(g["s"] > 0 for g in r.grid)  # the sweep explores s > 0


def test_stickiness_gates_the_headline():
    # sticky labels (the standard fixture): e1's later fraud follows an
    # earlier one -> stickiness = P(y|prior)/base = 1.0/0.5 = 2.0 -> headline
    df, _ = mapped()
    r = audit(df, label_delay_days=7.0)
    assert r.stats["stickiness"] == pytest.approx(2.0)
    assert r.stats["labels_propagate"]
    assert "THE NUMBER NOBODY HAS" in r.to_text()

    # independent labels: each entity frauds at most once, never after a
    # prior fraud -> stickiness 0 -> refuse the first-hit headline
    f = frame().assign(bad=[0, 1, 0, 1, 1, 0])
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "score": "s"},
        label_delay_days=7.0, source="test")
    r2 = audit(contract.apply_mapping(f, m), label_delay_days=7.0)
    assert not r2.stats["labels_propagate"]
    txt = r2.to_text()
    assert "ORDINARY RECALL" in txt
    assert "THE NUMBER NOBODY HAS" not in txt

    rep = contract.check(contract.apply_mapping(f, m), m)
    assert any("entity-independent" in w or "not be headlined" in w
               for w in rep.warnings)


def test_top_level_api_and_version_come_from_metadata():
    """PyPI 1.0.1 shipped __version__ = "0.1.0" and an empty namespace.
    Version must come from installed metadata (single source of truth:
    pyproject), and the documented API must be importable from the top."""
    import importlib.metadata

    import strikeone

    assert strikeone.__version__ == importlib.metadata.version("strikeone")
    assert strikeone.__version__ != "0.1.0"
    for name in ("audit", "route", "policy", "check",
                 "Mapping", "apply_mapping", "read_source", "ContractError"):
        assert name in strikeone.__all__
        assert hasattr(strikeone, name)
    # the exported audit is the real engine, end to end
    from strikeone import examples
    raw, m = examples.resolve("synthetic")
    res = strikeone.audit(strikeone.apply_mapping(raw, m),
                          label_delay_days=m.label_delay_days)
    assert res.stats["rows"] == len(raw)
    # submodules stay importable alongside the same-named exports
    from strikeone.audit import DEFAULT_CAPACITY  # noqa: F401
    from strikeone.route import route as route_fn
    assert callable(route_fn)
