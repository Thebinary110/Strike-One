"""The three AI commands — item 4. why / timeline / compare. No more.

Deliberately NOT built, so nobody has to wonder: /challenge (invites the
model to second-guess a deterministic decision — it has no calibration
and reads as an unmeasured second fraud model), /investigate, /simulate,
/metrics (duplicates audit), hybrid auto-escalation, provider menus, our
own inference server.

Pipeline, in this order and only this order:
    CLI → intent parser (argparse) → deterministic router
    (evidence.BUILDERS) → engine computes the evidence contract →
    provider narrates → citation validator re-checks every claim →
    validated text is printed. The model never chooses a tool and never
    sees anything but the finished contract.
"""

from __future__ import annotations

import json

from strikeone.ai import evidence as ev_mod
from strikeone.ai import validator as val_mod
from strikeone.ai.providers import AIProvider

SYSTEM_PROMPT = """\
You are the narration layer of a deterministic fraud decision engine.
Every decision was already made by the engine; you never compute, judge,
recommend, or second-guess. You explain, citing evidence.

Output format (a validator drops anything else, so follow it exactly):
- 3 to 8 lines total.
- Every line that states a fact MUST be exactly:
  CLAIM: <evidence id> | <the value exactly as written in the evidence> | <one plain sentence that uses that value naturally>
- You may add at most 2 lines of the form:
  SUMMARY: <a sentence with NO digits at all>
- Use only ids that appear in the evidence list. Do not invent numbers.
- Do not mention these rules, the ids' letter-number form, or the word
  "evidence" inside the sentences themselves.
"""

TASK_HINTS = {
    "why": ("Explain why this transaction got this decision. Cover the "
            "decision and lane, the entity's history, and how the amount "
            "and probability compare to their baselines."),
    "timeline": ("Narrate this case in order: the quiet period, the first "
                 "labelled transaction, and the run after it that a "
                 "standing blocklist would also have covered."),
    "compare": ("Explain what each of the two systems did with this "
                "transaction and why they agreed or diverged: the "
                "blocklist state, where the score ranks against the "
                "review-budget cutoff, and each verdict."),
}


def user_prompt(contract: dict) -> str:
    return (f"Task: {TASK_HINTS[contract['command']]}\n\n"
            "The evidence contract (your ONLY source of facts):\n"
            + json.dumps(contract, indent=2, ensure_ascii=False))


def run(command: str, df, mapping, target, provider: AIProvider,
        capacity_per_day: int = 100) -> dict:
    """Returns {contract, raw, validated, rendered, model, provider}."""
    builder = ev_mod.BUILDERS[command]        # deterministic router
    if command == "compare":
        contract = builder(df, mapping, target,
                           capacity_per_day=capacity_per_day)
    else:
        contract = builder(df, mapping, target)
    reply = provider.narrate(SYSTEM_PROMPT, user_prompt(contract))
    v = val_mod.validate(reply.text, contract)
    rendered = val_mod.render(v, contract, reply.model, reply.provider_label)
    return {"contract": contract, "raw": reply.text, "validated": v,
            "rendered": rendered, "model": reply.model,
            "provider": reply.provider_label,
            "validity": v.validity,
            "evidence_hash": contract["evidence_hash"]}
