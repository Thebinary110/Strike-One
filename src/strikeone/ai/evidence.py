"""The evidence contract — item 1 of the AI layer, built first, frozen.

A deterministic JSON document produced entirely by the existing engine
BEFORE any model is asked to speak. Every provider receives exactly this
and nothing else. The model never adds, removes or alters a field.

Frozen schema, contract_version 1.0 (top-level keys, exactly these):

    contract_version, evidence_hash, command, transaction_id, case_id,
    decision, lane, fraud_probability, episode_state, evidence, policy

Each evidence item has exactly: id, feature, value, baseline, source.
`evidence_hash` is the sha256 of the canonicalised contract (sorted keys,
compact separators, the hash field itself excluded), so any narration can
be traced to the exact evidence that produced it.

Invariants (asserted by tests):
- no raw transaction rows: evidence carries named, derived facts only;
- the sealed holdout is never read (strikeone.seal is not touched here);
- built twice on the same frame, the contract is byte-identical.
"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from strikeone import entity as entity_mod
from strikeone import metrics as M
from strikeone.contract import ContractError, Mapping
from strikeone.policy_engine import CENTRAL

CONTRACT_VERSION = "1.0"
TOP_KEYS = ["contract_version", "evidence_hash", "command",
            "transaction_id", "case_id", "decision", "lane",
            "fraud_probability", "episode_state", "evidence", "policy"]
ITEM_KEYS = ["id", "feature", "value", "baseline", "source"]
ACTION_NAMES = {0: "APPROVE", 1: "STEP_UP", 2: "BLOCK"}


def _round(v):
    if isinstance(v, (float, np.floating)):
        return round(float(v), 4)
    if isinstance(v, (int, np.integer)):
        return int(v)
    return v


def canonical_hash(contract: dict) -> str:
    body = {k: v for k, v in contract.items() if k != "evidence_hash"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _finish(contract: dict) -> dict:
    assert list(contract) == TOP_KEYS or set(contract) == set(TOP_KEYS)
    for item in contract["evidence"]:
        assert list(item) == ITEM_KEYS, f"evidence item keys drifted: {item}"
    contract["evidence_hash"] = canonical_hash(contract)
    return {k: contract[k] for k in TOP_KEYS}


def _prepare(df: pd.DataFrame, mapping: Mapping):
    """Engine-side derived state shared by all three builders."""
    d = df.sort_values(["t", "transaction_id"]).reset_index(drop=True)
    has_label = "label" in d.columns and not d["label"].isna().any()
    if not has_label:
        raise ContractError(
            "the AI layer explains decisions against labelled history; "
            "map a label column first (--map label=<col>)")
    y = d["label"].to_numpy().astype(int)
    ent = d["entity"].astype(str).to_numpy()
    t = d["t"].to_numpy().astype(np.int64)
    tb = d["transaction_id"].to_numpy()
    delay = float(mapping.label_delay_days)
    bl = entity_mod.pit_delayed_label_stats(
        pd.Series(ent), t, y, tb, delay_days=delay, prefix="u")
    knowable = np.nan_to_num(bl["u_fraud_rate"].to_numpy()
                             * bl["u_labeled_cnt"].to_numpy())
    flag = knowable > 0
    grp = pd.Series(y).groupby(pd.Series(ent))
    prior_frauds_any_age = (grp.cumsum() - pd.Series(y)).to_numpy()
    prior_txns = grp.cumcount().to_numpy()
    return d, y, ent, t, delay, flag, knowable, prior_frauds_any_age, prior_txns


def _policy_block(d: pd.DataFrame) -> dict | None:
    if "p" not in d.columns or d["p"].isna().all():
        return None
    prm = M.CostParams(**CENTRAL)
    ec = M.expected_cost_matrix(d["p"].to_numpy(float),
                                d["amount"].to_numpy(float), prm)
    mix = np.bincount(ec.argmin(axis=1), minlength=3)
    return {"approve": int(mix[0]), "step_up": int(mix[1]),
            "block": int(mix[2]),
            "params": {k: _round(v) for k, v in CENTRAL.items()}}


def build_why(df: pd.DataFrame, mapping: Mapping, transaction_id) -> dict:
    d, y, ent, t, delay, flag, knowable, prior_any, prior_n = \
        _prepare(df, mapping)
    hits = np.where(d["transaction_id"].astype(str).to_numpy()
                    == str(transaction_id))[0]
    if len(hits) == 0:
        raise ContractError(f"transaction {transaction_id!r} not found")
    i = int(hits[0])
    amount = float(d["amount"].iloc[i])
    e_rows = np.where(ent == ent[i])[0]
    prior_rows = e_rows[e_rows < i]
    prior_amt_mean = (float(d["amount"].iloc[prior_rows].mean())
                      if len(prior_rows) else None)

    lane = 1 if flag[i] else 2
    p_i = None
    if "p" in d.columns and not pd.isna(d["p"].iloc[i]):
        p_i = float(d["p"].iloc[i])
    if lane == 1:
        decision = "BLOCK"
    elif p_i is not None:
        prm = M.CostParams(**CENTRAL)
        ec = M.expected_cost_matrix(np.array([p_i]), np.array([amount]), prm)
        decision = ACTION_NAMES[int(ec.argmin(axis=1)[0])]
    else:
        decision = None
    if flag[i]:
        state = "already flagged"
    elif y[i] == 1 and prior_any[i] == 0:
        state = "first attempt"
    else:
        state = "no prior flags"

    ev = [
        {"id": "F1", "feature": "decision", "value": decision,
         "baseline": None,
         "source": "expected-cost argmin at frozen central params"
                   if lane == 2 else "lane-1 blocklist rule"},
        {"id": "F2", "feature": "lane", "value": lane, "baseline": None,
         "source": "two-lane router (point-in-time blocklist)"},
        {"id": "F3", "feature": "episode_state", "value": state,
         "baseline": None, "source": "episode roles, global stream"},
        {"id": "F4", "feature": "prior_transactions_on_entity",
         "value": int(prior_n[i]),
         "baseline": _round(float(np.median(prior_n))),
         "source": "point-in-time entity history (strikeone.entity)"},
        {"id": "F5", "feature": "knowable_prior_frauds_on_entity",
         "value": int(round(knowable[i])),
         "baseline": _round(float(knowable.mean())),
         "source": f"labels at least {delay:g} days old at decision time"},
        {"id": "F6", "feature": "amount", "value": _round(amount),
         "baseline": _round(float(d["amount"].median())),
         "source": "amount column vs population median"},
    ]
    if prior_amt_mean is not None:
        ev.append({"id": "F7", "feature": "entity_prior_mean_amount",
                   "value": _round(prior_amt_mean), "baseline": None,
                   "source": "mean amount of this entity's earlier rows"})
    if p_i is not None:
        ev.append({"id": "F8", "feature": "fraud_probability",
                   "value": _round(p_i),
                   "baseline": _round(float(d["p"].mean())),
                   "source": "calibrated p column (baseline: its mean)"})
    if "score" in d.columns and not pd.isna(d["score"].iloc[i]):
        pct = float((d["score"] < d["score"].iloc[i]).mean() * 100)
        ev.append({"id": "F9", "feature": "score_percentile",
                   "value": _round(pct), "baseline": 50.0,
                   "source": "rank of the score column within this file"})

    return _finish({
        "contract_version": CONTRACT_VERSION, "evidence_hash": "",
        "command": "why", "transaction_id": str(transaction_id),
        "case_id": None, "decision": decision, "lane": lane,
        "fraud_probability": _round(p_i) if p_i is not None else None,
        "episode_state": state, "evidence": ev, "policy": _policy_block(d),
    })


def build_timeline(df: pd.DataFrame, mapping: Mapping, case_id) -> dict:
    d, y, ent, t, delay, flag, knowable, prior_any, prior_n = \
        _prepare(df, mapping)
    rows = np.where(ent == str(case_id))[0]
    if len(rows) == 0:
        raise ContractError(f"case (entity) {case_id!r} not found")
    yy = y[rows]
    n_fraud = int(yy.sum())
    day = (t[rows] - t.min()) / 86400.0
    ev = [
        {"id": "T1", "feature": "case_transactions", "value": int(len(rows)),
         "baseline": None, "source": "all rows for this entity"},
    ]
    if n_fraud == 0:
        state = "no prior flags"
        ev.append({"id": "T2", "feature": "labelled_frauds_in_case",
                   "value": 0, "baseline": None,
                   "source": "label column over the case"})
    else:
        first = int(np.argmax(yy == 1))
        quiet = int(first)
        coverable = int(flag[rows][yy == 1].sum())
        state = "already flagged" if n_fraud > 1 else "first attempt"
        ev += [
            {"id": "T2", "feature": "quiet_transactions_before_first_fraud",
             "value": quiet, "baseline": None,
             "source": "rows before the case's first labelled transaction"},
            {"id": "T3", "feature": "first_fraud_day_index",
             "value": _round(float(day[first])), "baseline": None,
             "source": "days since the start of this file"},
            {"id": "T4", "feature": "first_fraud_amount",
             "value": _round(float(d["amount"].iloc[rows[first]])),
             "baseline": _round(float(d["amount"].iloc[rows[:first]].mean()))
             if first else None,
             "source": "amount vs the case's own quiet-period mean"},
            {"id": "T5", "feature": "labelled_frauds_in_case",
             "value": n_fraud, "baseline": None,
             "source": "label column over the case"},
            {"id": "T6", "feature": "blocklist_coverable_in_case",
             "value": coverable, "baseline": None,
             "source": f"fraud rows where a {delay:g}-day-delayed blocklist "
                       "already knew this entity"},
            {"id": "T7", "feature": "case_fraud_amount_total",
             "value": _round(float(d["amount"].iloc[rows][yy == 1].sum())),
             "baseline": None, "source": "sum of labelled-fraud amounts"},
        ]
    return _finish({
        "contract_version": CONTRACT_VERSION, "evidence_hash": "",
        "command": "timeline", "transaction_id": None,
        "case_id": str(case_id), "decision": None, "lane": None,
        "fraud_probability": None, "episode_state": state,
        "evidence": ev, "policy": None,
    })


def build_compare(df: pd.DataFrame, mapping: Mapping, transaction_id,
                  capacity_per_day: int = 100) -> dict:
    d, y, ent, t, delay, flag, knowable, prior_any, prior_n = \
        _prepare(df, mapping)
    if "score" not in d.columns or d["score"].isna().all():
        raise ContractError("compare needs a score column (--map score=...)")
    hits = np.where(d["transaction_id"].astype(str).to_numpy()
                    == str(transaction_id))[0]
    if len(hits) == 0:
        raise ContractError(f"transaction {transaction_id!r} not found")
    i = int(hits[0])
    days = max((t.max() - t.min()) / 86400.0, 1.0)
    budget = int(round(capacity_per_day * days))
    s = d["score"].to_numpy(float)
    single_alert = M.alerts_at_budget(s, budget)
    lane2 = ~flag
    k2 = min(budget, int(lane2.sum()))
    two_alert = flag | M.alerts_at_budget(np.where(lane2, s, -np.inf), k2)
    cutoff = float(np.sort(s)[-budget]) if budget <= len(s) else float("-inf")
    single_v = "alert" if single_alert[i] else "no alert"
    two_v = ("blocked by the lane-1 blocklist" if flag[i]
             else ("alert" if two_alert[i] else "no alert"))
    state = ("already flagged" if flag[i]
             else ("first attempt" if y[i] == 1 and prior_any[i] == 0
                   else "no prior flags"))
    ev = [
        {"id": "C1", "feature": "blocklist_state",
         "value": "flagged" if flag[i] else "not flagged", "baseline": None,
         "source": f"point-in-time blocklist, {delay:g}-day label delay"},
        {"id": "C2", "feature": "score", "value": _round(float(s[i])),
         "baseline": _round(float(s.mean())),
         "source": "score column (baseline: its mean)"},
        {"id": "C3", "feature": "score_percentile",
         "value": _round(float((s < s[i]).mean() * 100)), "baseline": 50.0,
         "source": "rank of the score within this file"},
        {"id": "C4", "feature": "review_budget_cutoff_score",
         "value": _round(cutoff), "baseline": None,
         "source": f"top-{budget:,} alerts at {capacity_per_day}/day "
                   f"over {days:.1f} days"},
        {"id": "C5", "feature": "single_lane_scorer_verdict",
         "value": single_v, "baseline": None,
         "source": "score ranking alone, same budget"},
        {"id": "C6", "feature": "two_lane_system_verdict",
         "value": two_v, "baseline": None,
         "source": "blocklist lane first, scorer on the rest"},
    ]
    # the divergence mechanism is determined by the ENGINE, not left to
    # the model's interpretation (a digit-free wrong reading slips past a
    # numeric validator; a citable string does not)
    if single_alert[i] == two_alert[i] and not flag[i]:
        mech = "both systems reached the same verdict; no divergence"
    elif flag[i]:
        mech = ("the blocklist lane knew this entity from a prior "
                "labelled fraud; the score ranking is irrelevant in "
                "lane 1")
    elif two_alert[i] and not single_alert[i]:
        mech = ("routing freed capacity: the same review budget spread "
                "over fewer lane-2 candidates lowers the cutoff below "
                "this score")
    else:
        mech = ("the single-lane ranking spent budget on rows the "
                "blocklist lane would have absorbed, reaching deeper "
                "into the file")
    ev.append({"id": "C7", "feature": "divergence_mechanism",
               "value": mech, "baseline": None,
               "source": "deterministic comparison of the two alert sets"})
    return _finish({
        "contract_version": CONTRACT_VERSION, "evidence_hash": "",
        "command": "compare", "transaction_id": str(transaction_id),
        "case_id": None, "decision": two_v, "lane": 1 if flag[i] else 2,
        "fraud_probability": None, "episode_state": state,
        "evidence": ev, "policy": None,
    })


# The deterministic tool router (item 3): CLI intent -> builder. The model
# is not in this dict and never sees it; a hallucinated tool choice is
# impossible by construction.
BUILDERS = {"why": build_why, "timeline": build_timeline,
            "compare": build_compare}
