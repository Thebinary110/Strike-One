"""The citation validator — item 2, the headline of the AI layer.

The model must emit structured lines:

    CLAIM: <source_id> | <value> | <one plain sentence using that value>
    SUMMARY: <sentence with no digits>

After generation, every CLAIM is re-checked against the evidence contract
it was generated from: the source_id must exist and the quoted value must
match the evidence value (strings: case-insensitive exact; numbers: equal
after rounding the evidence to the precision the model quoted, so honest
rounding passes and a wrong digit fails). FAIL CLOSED: a line that fails
validation is not printed; a short note says what was dropped and why.
Every invocation reports a validity rate: "N of N claims validated".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CLAIM_RE = re.compile(r"^\s*CLAIM:\s*([A-Za-z0-9_.]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$")
SUMMARY_RE = re.compile(r"^\s*SUMMARY:\s*(.+?)\s*$")


@dataclass
class Validated:
    lines: list = field(default_factory=list)      # printable sentences
    dropped: list = field(default_factory=list)    # (reason strings)
    total_claims: int = 0
    valid_claims: int = 0

    @property
    def validity(self) -> str:
        return f"{self.valid_claims} of {self.total_claims} claims validated"


def _index(contract: dict) -> dict:
    return {item["id"]: item for item in contract.get("evidence", [])}


def _value_matches(evidence_value, quoted: str) -> bool:
    if evidence_value is None:
        return quoted.strip().lower() in ("none", "null", "n/a")
    if isinstance(evidence_value, str):
        return quoted.strip().lower() == evidence_value.strip().lower()
    q = quoted.strip().rstrip("%").replace(",", "")
    try:
        qv = float(q)
    except ValueError:
        return False
    ev = float(evidence_value)
    if abs(qv - ev) <= 1e-9 * max(1.0, abs(ev)):
        return True
    decimals = len(q.split(".")[1]) if "." in q else 0
    return round(ev, decimals) == qv


NUM_TOKEN_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Decision-bearing words are factual claims even without digits ("the
# block should be lifted", "the transaction is legitimate"). They are
# validated like numbers: in a CLAIM sentence they must be vouched for by
# the CITED evidence item itself (its feature or value carries the word,
# e.g. decision=BLOCK vouches "blocked"); in a SUMMARY they are dropped
# outright. Word-boundary forms only - "blocklist" is a system component,
# not a decision, and does not match.
DECISION_RE = re.compile(
    r"\b(approv(?:e|es|ed|ing|al)|block(?:ed|s|ing)?|legitimate(?:ly)?|"
    r"fraudulent(?:ly)?|lift(?:ed|s|ing)?|den(?:y|ies|ied|ying)|"
    r"step[\s-]?up|declin(?:e|es|ed|ing))\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


_DECISION_STEMS = ("approv", "block", "legitimate", "fraudulent", "lift",
                   "den", "stepup", "declin")


def _unvouched_decision_word(sentence: str, item: dict) -> str | None:
    """A decision-bearing word in the sentence whose STEM the cited
    evidence item's own feature/value does not carry ("blocked" is vouched
    by decision=BLOCK; "approved" is not vouched by a prior-count item)."""
    vouched = _normalize(str(item["feature"]) + str(item["value"]))
    for m in DECISION_RE.finditer(sentence):
        word = _normalize(m.group(0))
        stem = next(s for s in _DECISION_STEMS if word.startswith(s))
        if stem not in vouched:
            return m.group(0)
    return None


def _numeric_pool(contract: dict) -> list:
    """Every number the contract vouches for: evidence values, baselines,
    lane, fraud_probability, and the policy block."""
    pool = []
    for item in contract.get("evidence", []):
        pool += [item["value"], item["baseline"]]
    pool += [contract.get("lane"), contract.get("fraud_probability")]
    pol = contract.get("policy")
    if pol:
        pool += [pol["approve"], pol["step_up"], pol["block"],
                 *pol["params"].values()]
    return [v for v in pool if isinstance(v, (int, float))]


def _unvouched_number(sentence: str, contract: dict) -> str | None:
    """A digit token in the sentence that matches nothing in the contract.
    Every printed number must be vouched for, not just the claim's value."""
    pool = _numeric_pool(contract)
    for tok in NUM_TOKEN_RE.findall(sentence):
        if not any(_value_matches(v, tok) for v in pool):
            return tok
    return None


def validate(raw_text: str, contract: dict) -> Validated:
    """Fail-closed filter of a model reply against its evidence contract."""
    idx = _index(contract)
    out = Validated()
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        m = CLAIM_RE.match(line)
        if m:
            out.total_claims += 1
            sid, quoted, sentence = m.group(1), m.group(2), m.group(3)
            item = idx.get(sid)
            if item is None:
                out.dropped.append(
                    f"{sid}: cites an evidence id that does not exist")
                continue
            if not _value_matches(item["value"], quoted):
                out.dropped.append(
                    f"{sid}: quoted {quoted!r}, evidence says "
                    f"{item['value']!r}")
                continue
            bad = _unvouched_number(sentence, contract)
            if bad is not None:
                out.dropped.append(
                    f"{sid}: sentence contains a number the evidence does "
                    f"not vouch for ({bad})")
                continue
            badw = _unvouched_decision_word(sentence, item)
            if badw is not None:
                out.dropped.append(
                    f"{sid}: decision-bearing word {badw!r} is not vouched "
                    "for by the cited evidence")
                continue
            out.valid_claims += 1
            out.lines.append(f"{sentence} [{sid}]")
            continue
        m = SUMMARY_RE.match(line)
        if m:
            if re.search(r"\d", m.group(1)):
                out.dropped.append(
                    "summary line contained digits (numbers must be CLAIMs)")
                continue
            dw = DECISION_RE.search(m.group(1))
            if dw:
                out.dropped.append(
                    f"summary asserted a decision ({dw.group(0)!r}) without "
                    "a citation (decisions must be CLAIMs)")
                continue
            out.lines.append(m.group(1))
            continue
        out.dropped.append(f"unstructured line dropped: {line.strip()[:40]!r}")
    return out


def render(v: Validated, contract: dict, model: str, provider_label: str,
           width: int = 74) -> str:
    L = []
    for line in v.lines:
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            cut = width if cut <= 0 else cut
            L.append("  " + line[:cut])
            line = "    " + line[cut:].strip()
        L.append("  " + line)
    if v.dropped:
        L.append("")
        L.append(f"  note: {len(v.dropped)} line(s) dropped by the "
                 "citation validator:")
        for r in v.dropped:
            L.append(f"    - {r}")
    L.append("")
    L.append(f"  citations: {v.validity}"
             f" · evidence sha256:{contract['evidence_hash'][:12]}")
    L.append(f"  narrated by: {model} ({provider_label}) — every number "
             "above was computed")
    L.append("  by the engine and re-checked against the evidence contract "
             "before printing")
    return "\n".join(L)
