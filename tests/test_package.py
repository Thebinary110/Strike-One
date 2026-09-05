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


# ---------------- external QA round 2: seven reported bugs ----------------

def test_delay_zero_is_not_circular():
    """--delay 0: a row's own label must not flag its own entity at its
    own decision time (was: side='right' included the row itself, so the
    blocklist circularly 'recovered 100.0%' of fraud)."""
    f = frame().assign(bad=[0, 1, 1, 0, 1, 0])
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "score": "s"},
        label_delay_days=0.0, source="test")
    df = contract.apply_mapping(f, m)
    r = audit(df, label_delay_days=0.0)
    assert r.blocklist["recovered_share"] < 1.0
    # flagged => strictly-prior fraud => role is propagated, never first
    # hit: the blocklist can still not catch first hits, and the prose
    # prints the COMPUTED count (was: JSON said 38, prose hardcoded "0")
    assert r.blocklist["first_strike_catches"] == 0
    txt = r.to_text()
    if "first-hit catches." in txt:
        assert f"{r.blocklist['first_strike_catches']:,} "                "first-hit catches." in txt


def test_zero_fraud_is_refused_and_json_is_valid():
    """No positive labels -> check refuses (nothing to audit) instead of
    emitting ROC-AUC NaN; and no to_json output ever contains bare NaN
    (invalid JSON for jq / JSON.parse)."""
    f = frame().assign(bad=0)
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "score": "s"},
        label_delay_days=7.0, source="test")
    rep = contract.check(contract.apply_mapping(f, m), m)
    assert not rep.ok
    assert any("no fraud to audit" in e for e in rep.errors)
    assert contract.json_safe(float("nan")) is None
    assert contract.json_safe({"a": [1.0, float("inf")]}) == {"a": [1.0, None]}
    df, _ = mapped()
    assert "NaN" not in audit(df, label_delay_days=7.0).to_json()


def test_entity_named_fernando_is_not_a_null_component():
    """'nan' must match whole pooled components, not substrings."""
    f = frame().assign(who=["fernando", "fernando", "fernando",
                            "hernandez", "anand", "anand"])
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "score": "s"},
        label_delay_days=7.0, source="test")
    f = f.assign(bad=[0, 1, 0, 1, 0, 1])
    df = contract.apply_mapping(f, m)
    assert audit(df, label_delay_days=7.0).stats["entity_resolution"] == 1.0
    rep = contract.check(df, m)
    assert rep.stats["entity_rows_with_null_component"].startswith("0.0%")
    # a genuinely pooled component still counts
    f2 = f.assign(who=["fernando", None, "fernando",
                       "hernandez", "anand", "anand"])
    df2 = contract.apply_mapping(f2, m)
    assert audit(df2, label_delay_days=7.0).stats["entity_resolution"] < 1.0


def test_capacity_zero_is_refused_not_silently_replaced():
    df, _ = mapped()
    for bad_cap in (0, -5):
        with pytest.raises(ValueError, match="positive"):
            audit(df, label_delay_days=7.0, capacity_per_day=bad_cap)


def test_route_and_policy_get_the_same_contract_gate(tmp_path, monkeypatch, capsys):
    """Duplicate transaction ids must refuse in route/policy exactly as in
    audit (was: degenerate 'infx' lift tables instead of refusal)."""
    from strikeone import cli
    f = frame().assign(bad=[0, 1, 0, 1, 0, 1], txid=[1, 1, 2, 2, 3, 3])
    src = tmp_path / "dup.csv"
    f.to_csv(src, index=False)
    monkeypatch.chdir(tmp_path)
    maps = ["--map", "transaction_id=txid", "--map", "timestamp=when",
            "--map", "amount=amt", "--map", "entity=who",
            "--map", "label=bad", "--map", "score=s"]
    for cmd in ("route", "policy"):
        with pytest.raises(SystemExit) as ex:
            cli.main([cmd, str(src), *maps])
        assert ex.value.code == 2, f"{cmd} must refuse duplicated ids"
        assert "duplicated" in capsys.readouterr().err


def test_policy_refuses_uncalibrated_p():
    """p > 1 is not a probability; policy must refuse loudly, not price
    nonsense (was: silently recommended a mix costing more than
    approve-all)."""
    from strikeone.policy_engine import policy
    f = frame().assign(bad=[0, 1, 0, 1, 0, 1], praw=[0.1, 1.7, 0.2, 0.9,
                                                     0.05, 1.2])
    m = contract.Mapping(
        columns={"transaction_id": "txid", "timestamp": "when",
                 "amount": "amt", "entity": ["who"], "label": "bad",
                 "p": "praw"},
        label_delay_days=7.0, source="test")
    df = contract.apply_mapping(f, m)
    with pytest.raises(ValueError, match="not\\s+.*probability|not a"):
        policy(df, {})
    rep = contract.check(df, m)
    assert not rep.ok and any("not a" in e and "probability" in e
                              for e in rep.errors)


def test_route_lift_is_undefined_at_zero_over_zero():
    """0.0% -> 0.0% is 0/0 (undefined), not 'infx'; and x/0 with x>0 has
    no finite ratio. JSON carries null; the table prints '-' / 'from 0'."""
    from strikeone.route import RouteResult
    res = RouteResult(
        lane1={"rows": 2, "row_share": 0.01, "entities": 1},
        curve=[
            {"per_day": 1, "budget": 5, "fs_recall_off": 0.0,
             "fs_recall_on": 0.0, "lift": None, "primary": False},
            {"per_day": 5, "budget": 25, "fs_recall_off": 0.0,
             "fs_recall_on": 0.25, "lift": None, "primary": False},
            {"per_day": 10, "budget": 50, "fs_recall_off": 0.2,
             "fs_recall_on": 0.5, "lift": 2.5, "primary": True},
        ])
    txt = res.to_text()
    assert "inf" not in txt
    lines = txt.splitlines()
    assert any(l.rstrip().endswith("-") for l in lines)
    assert any(l.rstrip().endswith("from 0") for l in lines)
    assert any(l.rstrip().endswith("2.50x") for l in lines)
    assert "Infinity" not in res.to_json() and "NaN" not in res.to_json()
    # and the engine itself never emits inf in the curve
    df, _ = mapped()
    r = route(df, label_delay_days=7.0)
    assert all(c["lift"] is None or np.isfinite(c["lift"]) for c in r.curve)


def test_top_level_namespace_has_no_import_leaks():
    """Only __all__ (plus submodules and dunders) may be visible; the
    importlib.metadata exception class leaked in 1.0.2."""
    import sys
    import types

    import strikeone

    assert not hasattr(strikeone, "PackageNotFoundError")
    for name in dir(strikeone):
        if name.startswith("_") or name in strikeone.__all__:
            continue
        attr = getattr(strikeone, name)
        assert isinstance(attr, types.ModuleType) and \
            attr.__name__.startswith("strikeone"), \
            f"unexpected top-level name leaked: {name}"


def test_tui_launch_routing(monkeypatch, capsys):
    """Bundled-first TUI launch: node missing -> [tui]-extra hint; no
    bundle and no repo -> upgrade/clone pointer. No process is spawned."""
    from pathlib import Path as P

    from strikeone import cli

    # bundle present, node missing: point at the pip-managed runtime
    monkeypatch.setattr(cli, "_bundled_tui", lambda: P("/fake/cli.mjs"))
    monkeypatch.setattr(cli, "_find_node", lambda: None)

    class A: rest = []
    assert cli.cmd_tui(A) == 2
    assert 'strikeone[tui]' in capsys.readouterr().err
    # no bundle, no repo: upgrade or clone
    monkeypatch.setattr(cli, "_bundled_tui", lambda: None)
    monkeypatch.setattr(cli, "_find_node", lambda: None)
    monkeypatch.setattr(cli.config, "REPO_ROOT", P("/nonexistent"))
    assert cli.cmd_tui(A) == 2
    err = capsys.readouterr().err
    assert "no bundled TUI" in err and "git clone" in err
    # bundle present AND node present: it spawns exactly [node, bundle]
    monkeypatch.setattr(cli, "_bundled_tui", lambda: P("/fake/cli.mjs"))
    monkeypatch.setattr(cli, "_find_node", lambda: "/usr/bin/node")
    calls = {}

    def fake_call(cmd, env=None):
        calls["cmd"], calls["env"] = cmd, env
        return 0

    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    assert cli.cmd_tui(A) == 0
    assert calls["cmd"] == ["/usr/bin/node", "/fake/cli.mjs"]
    assert calls["env"]["STRIKEONE_ROOT"] == cli.os.getcwd()


def test_find_node_falls_back_to_pip_managed_runtime(monkeypatch, tmp_path):
    """strikeone[tui] installs nodejs-wheel-binaries, whose node binary
    lives inside site-packages (NOT on PATH); _find_node must find it."""
    import sys
    import types

    from strikeone import cli

    monkeypatch.setattr(cli.shutil, "which", lambda *_: None)
    fake = types.ModuleType("nodejs_wheel")
    (tmp_path / "bin").mkdir()
    node = tmp_path / "bin" / "node"
    node.write_text("#!/bin/sh\n")
    fake.__file__ = str(tmp_path / "__init__.py")
    monkeypatch.setitem(sys.modules, "nodejs_wheel", fake)
    assert cli._find_node() == str(node)
    del sys.modules["nodejs_wheel"]
    import builtins
    real_import = builtins.__import__

    def no_nodejs(name, *a, **k):
        if name == "nodejs_wheel":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_nodejs)
    assert cli._find_node() is None


def test_rpc_slash_command_backends(tmp_path, monkeypatch):
    """The TUI's / commands land on these rpc methods: AI disabled by
    default, evidence needs no model, capacity re-audits, provider chain
    reports the disabled state."""
    from strikeone.rpc import Session

    monkeypatch.chdir(tmp_path)          # no .strikeone-ai.toml here
    s = Session()
    s.init({"example": "synthetic"})
    # ai: disabled default is a message, not an error
    r = s.ai({"cmd": "why", "target": "11254"})
    assert r.get("disabled") and "strikeone ai setup" in r["text"]
    with pytest.raises(ValueError):
        s.ai({"cmd": "challenge", "target": "1"})
    # evidence: deterministic, no provider needed
    ev = s.evidence({"cmd": "why", "target": "11254"})
    assert '"contract_version": "1.0"' in ev["text"]
    with pytest.raises(ValueError):
        s.evidence({"cmd": "simulate", "target": "1"})
    # provider chain: disabled text
    assert "disabled" in s.provider_chain({})["text"]
    # audit honours a capacity change and re-computes
    a50 = s.audit({"capacity": 50})
    assert [b["per_day"] for b in a50["budgets"] if b["primary"]] == [50]
    a100 = s.audit({"capacity": 100})
    assert [b["per_day"] for b in a100["budgets"] if b["primary"]] == [100]


def test_chat_overview_contract_and_disabled_default(tmp_path, monkeypatch):
    """Free-form chat answers come from a hashed overview contract built
    from the session's own computed numbers - deterministic, schema v1.0,
    no raw rows - and chat is off until a provider is configured."""
    from strikeone.ai import evidence as E
    from strikeone.rpc import Session

    monkeypatch.chdir(tmp_path)
    s = Session()
    s.init({"example": "synthetic"})
    a = s._overview_contract()
    b = s._overview_contract()
    assert a == b, "overview contract must be deterministic"
    assert list(a) == E.TOP_KEYS and a["command"] == "chat"
    assert a["evidence_hash"] == E.canonical_hash(a)
    feats = {i["feature"] for i in a["evidence"]}
    assert {"rows", "fraud_cases", "first_hit_recall_at_budget",
            "blocklist_coverable_share_of_hits"} <= feats
    for i in a["evidence"]:
        assert isinstance(i["value"], (str, int, float, type(None)))
    r = s.chat({"question": "how many fraud cases?"})
    assert r.get("disabled") and "setup ollama" in r["text"]


def test_rpc_stream_raw_fallback_without_score(tmp_path, monkeypatch):
    """No score column: stream replays the raw transaction flow (marked
    raw) instead of erroring, so the panel is never dead."""
    from strikeone import contract as C
    from strikeone import examples
    from strikeone.rpc import Session

    monkeypatch.chdir(tmp_path)
    raw, m = examples.resolve("synthetic")
    df = C.apply_mapping(raw, m).drop(columns=["score"])
    s = Session(); s.df = df; s.mapping = m; s._arrays = None
    out = s.stream({"limit": 10})
    assert out.get("raw") is True
    assert len(out["rows"]) == 10
    assert out["rows"][0]["id"] and "day" in out["rows"][0]


def test_rpc_case_raises_on_unknown_entity(tmp_path, monkeypatch):
    """case cc_num" typing the column name instead of a real value must
    raise a clean, catchable error - not return an empty payload that
    later crashes the TUI's render on rows[0]."""
    from strikeone import contract as C
    from strikeone import examples
    from strikeone.rpc import Session

    monkeypatch.chdir(tmp_path)
    raw, m = examples.resolve("synthetic")
    s = Session(); s.df = C.apply_mapping(raw, m); s.mapping = m; s._arrays = None
    with pytest.raises(ValueError, match="not found"):
        s.case({"entity": "cc_num"})
