"""AI-layer invariants (items 1, 2, 5, 7, 8, 9 of the AI mandate).

Everything here runs offline with no provider, no key and no Ollama,
except the provider-independence test, which requires OPENROUTER_API_KEY
and skips cleanly without it.
"""

import json
import os
import sys

import numpy as np
import pytest

from strikeone import contract as C
from strikeone import examples
from strikeone.ai import aiconfig, commands
from strikeone.ai import evidence as E
from strikeone.ai import validator as V
from strikeone.ai.providers import AIProvider, Reply


@pytest.fixture(scope="module")
def synth():
    raw, m = examples.resolve("synthetic")
    return C.apply_mapping(raw, m), m


def _some_fraud_txn(df):
    return str(df[df["label"] == 1].iloc[40]["transaction_id"])


def _some_case(df):
    g = df[df["label"] == 1].groupby("entity").size()
    return str(g[g >= 2].index[0])


# ---------------------------------------------------------------- item 1

def test_contract_frozen_schema_versioned_and_deterministic(synth):
    df, m = synth
    txn = _some_fraud_txn(df)
    a = E.build_why(df, m, txn)
    b = E.build_why(df, m, txn)
    assert a == b, "the evidence contract must be deterministic"
    assert a["contract_version"] == "1.0"
    assert list(a) == E.TOP_KEYS
    for item in a["evidence"]:
        assert list(item) == E.ITEM_KEYS
    assert a["evidence_hash"] == E.canonical_hash(a)
    tl = E.build_timeline(df, m, _some_case(df))
    cp = E.build_compare(df, m, txn)
    for con in (tl, cp):
        assert list(con) == E.TOP_KEYS
        assert con["evidence_hash"] == E.canonical_hash(con)


def test_contract_never_reads_holdout_and_carries_no_raw_rows(synth, monkeypatch):
    df, m = synth
    from strikeone import seal

    def boom(*a, **k):
        raise AssertionError("the AI layer must never touch the holdout")

    monkeypatch.setattr(seal, "load_holdout", boom)
    txn = _some_fraud_txn(df)
    for con in (E.build_why(df, m, txn),
                E.build_timeline(df, m, _some_case(df)),
                E.build_compare(df, m, txn)):
        # named derived facts only — every value is a scalar, never a row
        for item in con["evidence"]:
            assert isinstance(item["value"], (str, int, float, type(None)))
            assert isinstance(item["baseline"], (int, float, type(None)))
        blob = json.dumps(con)
        assert "holdout" not in blob.lower()


# ---------------------------------------------------------------- item 2

def test_validator_rejects_falsified_claim(synth):
    """THE test: right source id, deliberately wrong value -> dropped."""
    df, m = synth
    con = E.build_why(df, m, _some_fraud_txn(df))
    f4 = next(i for i in con["evidence"] if i["id"] == "F4")
    truthful = f"CLAIM: F4 | {f4['value']} | The entity had made " \
               f"{f4['value']} earlier purchases."
    falsified = f"CLAIM: F4 | {int(f4['value']) + 2} | The entity had " \
                f"made {int(f4['value']) + 2} earlier purchases."
    phantom = "CLAIM: F99 | 42 | A number from nowhere."
    v = V.validate("\n".join([truthful, falsified, phantom]), con)
    assert v.total_claims == 3 and v.valid_claims == 1
    joined = "\n".join(v.lines)
    assert "earlier purchases. [F4]" in joined
    assert str(int(f4["value"]) + 2) not in joined   # fail closed: not printed
    assert any("F4" in d and "evidence says" in d for d in v.dropped)
    assert any("does not exist" in d for d in v.dropped)
    assert v.validity == "1 of 3 claims validated"


def test_validator_rounding_and_summary_rules(synth):
    df, m = synth
    con = E.build_why(df, m, _some_fraud_txn(df))
    f6 = next(i for i in con["evidence"] if i["id"] == "F6")  # amount
    rounded = f"{float(f6['value']):.1f}"
    ok = V.validate(f"CLAIM: F6 | {rounded} | It was about {rounded}.", con)
    assert ok.valid_claims == 1, "honest rounding must validate"
    wrong = V.validate(
        f"CLAIM: F6 | {float(f6['value']) + 1:.4f} | Off by one.", con)
    assert wrong.valid_claims == 0, "a wrong digit must fail"
    s = V.validate("SUMMARY: The pattern looks like 3 waves.", con)
    assert not s.lines and s.dropped, "summaries may not smuggle digits"
    # a claim whose VALUE is right but whose sentence smuggles a number
    # the contract does not vouch for is dropped whole
    f4 = next(i for i in con["evidence"] if i["id"] == "F4")
    smuggled = V.validate(
        f"CLAIM: F4 | {f4['value']} | The entity made {f4['value']} "
        "purchases totalling 99999.99.", con)
    assert smuggled.valid_claims == 0
    assert any("does not vouch" in d for d in smuggled.dropped)


def test_validator_blocks_uncited_decision_language(synth):
    """Digit-free decision assertions are factual claims too: they must be
    vouched for by the cited evidence or they are dropped (the stricter
    fix for the black-box QA's finding H)."""
    df, m = synth
    con = E.build_why(df, m, "11254")   # a lane-1 BLOCK contract
    # the original attack: an uncited decision in a digit-free summary
    v = V.validate("SUMMARY: This transaction is legitimate and the block "
                   "should be lifted.", con)
    assert not v.lines
    assert any("asserted a decision" in d for d in v.dropped)
    # a decision word vouched by the cited item itself passes
    ok = V.validate("CLAIM: F1 | BLOCK | The engine blocked this "
                    "transaction.", con)
    assert ok.valid_claims == 1
    # correct value, but a decision word the cited item does not vouch for
    f4 = next(i for i in con["evidence"] if i["id"] == "F4")
    bad = V.validate(f"CLAIM: F4 | {f4['value']} | With {f4['value']} prior "
                     "purchases it should be approved.", con)
    assert bad.valid_claims == 0
    assert any("decision-bearing" in d for d in bad.dropped)
    # "blocklist" is a component, not a decision: benign summaries pass
    s2 = V.validate("SUMMARY: The pattern is repetition on an entity the "
                    "blocklist already knew.", con)
    assert s2.lines and not s2.dropped


def test_provider_failure_is_a_clean_message(synth, tmp_path, monkeypatch, capsys):
    """An unreachable provider must never show a traceback (QA P1 #1)."""
    from strikeone import cli
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".strikeone-ai.toml").write_text(
        '[ai]\nprovider = "ollama"\nmodel = "x"\n'
        'base_url = "http://localhost:9"\n')
    with pytest.raises(SystemExit) as ex:
        cli.main(["ai", "why", "11254", "--example", "synthetic"])
    assert ex.value.code == 2
    err = capsys.readouterr().err
    assert "AI provider unavailable" in err
    assert "remains available" in err
    assert "Traceback" not in err


# ------------------------------------------------------------- items 3, 9

class FakeProvider(AIProvider):
    """Offline provider: echoes valid claims for the contract it is shown.
    Proves the pipeline (router -> engine -> narrate -> validate) with no
    network and no model."""

    def __init__(self):
        self.prompts = []

    def narrate(self, system_prompt, user_prompt):
        self.prompts.append(user_prompt)
        con = json.loads(user_prompt.split("facts):\n", 1)[1])
        lines = [f"CLAIM: {i['id']} | {i['value']} | "
                 f"The {i['feature'].replace('_', ' ')} was {i['value']}."
                 for i in con["evidence"][:4]]
        lines.append("SUMMARY: The engine decided; this is only narration.")
        return Reply(text="\n".join(lines), model="fake-1",
                     provider_label="test, offline")

    def chain_text(self):
        return "Provider: fake"


def test_router_is_deterministic_and_model_never_picks_tools(synth):
    df, m = synth
    assert set(E.BUILDERS) == {"why", "timeline", "compare"}, \
        "exactly three commands, no more (the mandate's item 4)"
    fp = FakeProvider()
    res = commands.run("why", df, m, _some_fraud_txn(df), fp)
    # the tool was chosen before the model saw anything:
    assert '"command": "why"' in fp.prompts[0]
    assert res["validated"].valid_claims == 4
    assert res["model"] == "fake-1"                 # the author is named
    assert res["evidence_hash"] == res["contract"]["evidence_hash"]
    assert "fake-1" in res["rendered"]
    with pytest.raises(KeyError):
        commands.run("challenge", df, m, "1", fp)   # not built, by design


# ---------------------------------------------------------------- item 5

def test_no_config_writer_can_persist_a_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("SOMETHING_API_KEY", "sk-verysecretvalue123")
    monkeypatch.setenv("OTHER_TOKEN", "tok-verysecretvalue456")
    cfg = tmp_path / "ai.toml"
    for leaked in ("sk-verysecretvalue123", "tok-verysecretvalue456"):
        with pytest.raises(aiconfig.CredentialLeakError):
            aiconfig.guarded_write(cfg, {"model": leaked})
    with pytest.raises(aiconfig.CredentialLeakError):
        aiconfig.guarded_write(cfg, {"api_key": "anything"})
    assert not cfg.exists(), "nothing may be written on refusal"
    # the honest path stores the env var's NAME only
    aiconfig.AIConfig(provider="openai-compatible", model="m",
                      base_url="https://example.test/v1",
                      api_key_env="SOMETHING_API_KEY").save(cfg)
    text = cfg.read_text()
    assert "SOMETHING_API_KEY" in text
    assert "sk-verysecretvalue123" not in text


# ---------------------------------------------------------------- item 7

def test_ai_disabled_by_default_and_audit_unchanged(tmp_path, monkeypatch, capsys):
    from strikeone import cli
    monkeypatch.chdir(tmp_path)                     # no config files here
    with pytest.raises(SystemExit) as ex:
        cli.main(["audit", "--example", "synthetic"])
    assert ex.value.code == 0
    out = capsys.readouterr().out
    assert "STRIKE ONE" in out and "THE NUMBER NOBODY HAS" in out
    # ai subcommand without a provider: clean refusal, clear pointer
    with pytest.raises(SystemExit) as ex:
        cli.main(["ai", "why", "12", "--example", "synthetic"])
    assert ex.value.code == 2
    err = capsys.readouterr().err
    assert "disabled by default" in err
    # --show-evidence works with no provider at all (engine-only)
    with pytest.raises(SystemExit) as ex:
        cli.main(["ai", "why", "12", "--example", "synthetic",
                  "--show-evidence"])
    assert ex.value.code == 0
    con = json.loads(capsys.readouterr().out)
    assert con["contract_version"] == "1.0" and con["evidence_hash"]


# ---------------------------------------------------------------- item 8

PINNED_SLUGS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "meta-llama/llama-3.1-8b-instruct",
    "google/gemini-2.5-flash",
]
# A zero-credit (free-tier) key cannot reach the paid pins; override the
# slug list without editing the test via
#   STRIKEONE_INDEPENDENCE_SLUGS="a/x:free,b/y:free" pytest -k independence
# STRIKEONE_OLLAMA_MODEL adds a local Ollama model to the same harness.


def _ollama_reachable(base="http://localhost:11434") -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(f"{base}/api/tags", timeout=2)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"),
                    reason="provider-independence harness needs "
                           "OPENROUTER_API_KEY; skipping cleanly")
def test_provider_independence_citation_validity(synth):
    """One fixed evidence set through several model families (plus local
    Ollama when present); the citation validator must pass for every one.
    A measured claim, not a demo."""
    from strikeone.ai.providers import (OllamaProvider,
                                        OpenAICompatibleProvider)
    df, m = synth
    txn = _some_fraud_txn(df)
    override = os.environ.get("STRIKEONE_INDEPENDENCE_SLUGS", "")
    slugs = [s.strip() for s in override.split(",") if s.strip()] \
        or PINNED_SLUGS
    providers = [(slug, OpenAICompatibleProvider(
        model=slug, base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY")) for slug in slugs]
    local = os.environ.get("STRIKEONE_OLLAMA_MODEL")
    if local and _ollama_reachable():
        providers.append((f"{local} (local ollama)",
                          OllamaProvider(model=local, think=False)))
    results = {}
    for name, p in providers:
        res = commands.run("why", df, m, txn, p)
        v = res["validated"]
        results[name] = (v.valid_claims, v.total_claims, res["model"])
        assert v.total_claims >= 3, f"{name}: too few structured claims"
        assert v.valid_claims == v.total_claims, \
            f"{name}: {v.validity}, dropped={v.dropped}"
    n = sum(r[1] for r in results.values())
    fams = {name.split("/")[0] for name in results}
    print(f"\ncitation validity: 100% of {n} claims across "
          f"{len(results)} models from {len(fams)} families")
    for name, (vc, tc, answered) in results.items():
        print(f"  {name}: {vc}/{tc} (answered by {answered})")
