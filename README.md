<div align="center">

# Strike One

**A reference fraud detector, measured on a sealed holdout — and the
episode-aware evaluation that selected it. Swap in your own scorer.**

[![PyPI](https://img.shields.io/pypi/v/strikeone)](https://pypi.org/project/strikeone/)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![License](https://img.shields.io/badge/license-Apache--2.0-green)
![Tests](https://img.shields.io/badge/tests-93%20passing-brightgreen)
![Offline](https://img.shields.io/badge/network%20calls-zero-black)

</div>

Fraud labels propagate: once a fraudster is confirmed, all their later
attempts get labelled fraud too. Standard metrics credit a model for
re-catching them — alerts a standing blocklist would also have covered.
Strike One measures that gap on **your** data, with **your** model, and
ships the reference detector the corrected evaluation selected.

- `strikeone onboard` - point it at an unfamiliar export and it proposes
  the column mapping (heuristics + your configured model, if any),
  validates every candidate against the data, and asks only where
  ambiguity matters - **the fraud label is always confirmed by a human**
- `strikeone audit` - your headline metric vs fraud cases caught at their
  **first labelled transaction**, blocklist-coverable alerts, and what a
  blocklist gets you free
- `strikeone route` - wrap the scorer you already run with a blocklist
  lane, and measure the lift (or learn it would not help, honestly)
- `strikeone policy` - your costs in, approve / verify / block out
- `strikeone tui` - all of it as a terminal app

Bring your own scorer. **Your data never leaves the machine**: no
telemetry, no network calls, anywhere.

## Prior art — read this before the numbers

The first-hit idea is not ours. Nguyen et al. (AISTATS 2022,
arXiv:2204.05265) state it verbatim — *"instead of considering the
transaction with the highest score, we consider the score predicted for
the first fraudulent transaction on the card"* — and the Fraud Detection
Handbook's Card Precision@k drops already-caught cards *by default*.
Delayed labels and the alert–feedback loop are Dal Pozzolo et al. (IEEE
TNNLS 2017); case-level evaluation is Hand et al. (JORS 2008); the cost
engine is a careful implementation of Elkan (IJCAI 2001) and Bahnsen et
al. — correct engineering, not a contribution. What this project adds is
narrow: **a measurement of how much label propagation bends model
*selection*** (the higher-AP model catches fewer cases at their first
labelled transaction, shown under a sealed holdout with pre-registered
predictions), and **the corrected evaluation packaged as a tool that runs
on your export**. Full genealogy, including the metric-inversion
literature we run backwards: [`reports/PRIOR_ART.md`](https://github.com/Thebinary110/Strike-One/blob/main/reports/PRIOR_ART.md).

## Install

```bash
pip install strikeone            # the Python core: check/audit/route/policy/ai
```

Or from source (needed for the TUI and the frozen IEEE-CIS study):

```bash
git clone https://github.com/Thebinary110/Strike-One && cd Strike-One
pip install -e .          # or: uv sync
```

Extras: `pip install "strikeone[db]"` for database-URL sources,
`"strikeone[tui]"` for a pip-managed Node runtime if you don't have
Node 18+, `"strikeone[research]"` to reproduce the study.

## Try it in 30 seconds

```bash
strikeone audit --example synthetic    # instant, generated demo data
```

With the worked study built (see `FINDINGS.md`),
`strikeone audit --example ieee-cis` prints, verbatim:

```text
STRIKE ONE  fraud-operation audit
──────────────────────────────────────────────────────────────────────────
WHAT WAS READ
  92,427 transactions over 32.0 days (relative timestamps)
  3,213 labelled fraud (3.48%); no rows were dropped
  the entity key resolves cleanly on 89.5% of rows; the rest pool into
  coarser identities, so every case count below leans conservative
  fraud labels assumed knowable 7 days after the transaction
  label stickiness: 14.8x the base rate (labels propagate across entities)

THE NUMBER YOU ALREADY HAVE
  average precision 0.4849, ROC-AUC 0.8553
  at a stated default of 100 reviews/day
  (pass --capacity with your real number):
  47% of fraud transactions caught, 1,676 good customers flagged

THE NUMBER NOBODY HAS
  54.0% of fraud CASES caught at their first labelled transaction
  at those same 100 reviews/day. Everything after a case's first
  transaction, a standing blocklist would also have covered.

WHERE YOUR ALERTS WENT
  of 3,199 alerts spent:
     790  caught a case at its first labelled transaction
     733  were alerts a standing blocklist would also have covered
          (48% of your correct alerts: later attempts in
          cases that had already begun)
   1,676  flagged good customers

WHAT A BLOCKLIST GETS YOU FOR FREE
  a plain blocklist, no model, recovers 12.9% of your labelled fraud
  by flagging 566 transactions at 73.0% precision, with 0 first-hit catches.
  At the same 566 alerts your scorer reaches 92.9% precision and catches
  283 cases at the first hit. Respectable precision, zero first hits:
  precision with no first-hit catches is exactly what it sells.

ONE THING TO DO NEXT
  about 23 of your 100 reviews/day went to cases that had already
  begun. How many of those a blocklist lane actually recovers depends on
  your 7-day label maturity. Measure it: strikeone route <your file>

AT OTHER REVIEW BUDGETS
  reviews/day txns caught   first-hit   blk-coverable good flagged
            1        1.0%        1.6%           25.8%            0
            2        2.0%        2.7%           38.1%            0
            5        4.9%        6.1%           43.3%            2
           10        9.6%       11.7%           44.3%           12
           20       18.2%       21.9%           45.2%           55
           50       36.2%       44.0%           44.6%          437
          100       47.4%       54.0%           48.1%        1,676 <-capacity
          200       57.8%       62.9%           50.4%        4,543
          500       72.7%       77.5%           51.5%       13,662

──────────────────────────────────────────────────────────────────────────
ASSUMED, NOT MEASURED
  cases are bounded by this file. Any fraudster already active before it
  starts counts here as a first hit, so first-hit counts are an
  upper bound. A longer window, or --history, tightens it.
  Fraud labels mature in 7 days here; slower maturity shrinks
  every blocklist figure above. Case boundaries come from your entity key;
  a coarser or finer key moves them. This audit evaluates only the score
  column you provided: no other model was applied to your traffic, and
  nothing about your data left this machine.
```

The command also prints why these numbers legitimately differ from the
frozen study reports (different scorer configuration, window-local case
boundaries, alert arithmetic). If your labels don't propagate across
entities (stickiness ≈ 1), the audit says so and refuses to headline
first-hit recall — on such data the corrected metric has nothing to add.

## What the sealed holdout said

The study behind the tool (full narrative: [`FINDINGS.md`](https://github.com/Thebinary110/Strike-One/blob/main/FINDINGS.md),
every figure: [`reports/stage7/canonical_comparisons.md`](https://github.com/Thebinary110/Strike-One/blob/main/reports/stage7/canonical_comparisons.md)):

- **The distortion is real and selects the wrong model.** Adding the
  entity-history features everyone adds buys +0.17 AP while *reducing*
  first-hit recall (−0.019, CI excluding zero, holdout).
- **The conclusion survives slower labels.** Rebuilding the evaluation
  blocklist at 1–30-day label maturity, the shipped system's first-hit
  edge stays positive with CIs excluding zero at every delay (+0.054 at
  1 day, +0.043 at 30). No reversal; no boundary to name.
- **A baseline we could not skip, reported because it surprised us.**
  On the headline metric — unweighted first-hit recall — ranking by
  amount alone catches **5.3% of cases at 5.5% precision** vs the
  shipped **58.3% at 45.7%** (100 reviews/day). But on *loss-weighted*
  first-hit recall the same no-model sort reaches **0.345, 73% of our
  0.473**, against a pre-registered prediction of 0.05–0.20. The
  mechanism is structural: any loss-weighted metric partially rewards
  amount-ranking by construction (its numerator is denominated in the
  ranking key). So the headline here is unweighted; loss-weighted
  figures are secondary and never quoted without the rank-by-amount row
  beside them.
- **Costs, out-of-sample and decomposed:** the three-action policy
  beats a validation-tuned fixed threshold on the holdout in **81 of 81
  declared economic corners** (per-corner bootstrap CIs excluding zero),
  median edge +14.4% of approve-all cost — but that is **mostly the
  value of having a step-up action at all, not of cost-derived
  thresholding**: amount-aware vs amount-blind three-action is 55/81
  with a central gap of 0.04% (Stage 4's own negative finding, kept).
  Most of the advantage is the action set, not the arithmetic. Stress-
  tested by widening the step-up-efficacy range to e ∈ [0.2, 0.95]
  after a reviewer challenged the original 0.6 floor (a post-hoc
  extension, stated as such; no new holdout access — computed from the
  committed replay artifact): unanimity holds down to **e = 0.5** and
  fails corner-by-corner below it; the median edge never goes negative.
  All under the stated counterfactual that a blocked fraud is fully
  avoided and a stepped-up one avoided with probability e. An earlier
  same-data version of this claim was withdrawn as near-tautological
  (Cawley & Talbot, JMLR 2010); this is the rebuilt one.

## Use it on your data - no code

Let onboarding propose the mapping - proposals are validated
deterministically against your data, auto-accepted only when unambiguous,
and the label, the entity key, and any competing timestamp are always
confirmed by you (a decision audit lands in `.strikeone.onboarding.json`):

```bash
strikeone onboard yourdata.parquet     # writes .strikeone.toml
strikeone audit  yourdata.parquet
```

With an AI provider configured, a **redacted** schema profile (column
names, dtypes, statistics, value shapes - never raw values unless you
pass `--share-samples`) goes to your model as a second proposer; the
exact egress path is printed before anything is sent. Without one, a
name/statistics heuristic proposes alone. Either way the model only ever
*proposes*: acceptance is deterministic validation plus you.

Or map columns by hand once, then every command works:

```bash
strikeone check  yourdata.parquet \
  --map transaction_id=txn_id --map timestamp=created_at \
  --map amount=amount --map entity=card_hash+email_hash \
  --map label=is_chargeback --delay 30 --save-config
strikeone audit  yourdata.parquet --capacity 50
```

| you need | what it is |
|---|---|
| `transaction_id` | one row = one transaction |
| `timestamp` | epoch seconds or ISO datetimes |
| `amount` | transaction amount |
| `entity` | who it belongs to (one or more columns, `a+b`) |
| `label` | 1 = confirmed fraud/chargeback, plus `--delay` (days until known) |
| `score` *(optional)* | your model's output |
| `p` *(optional)* | calibrated probability, only for `policy` |

Useful flags: `--capacity` (your real reviews/day) · `--history file`
(entities flagged before this window, tightens first-hit counts from
upper bound to measured) · `--json` (pipe anywhere, CI-friendly).
Readers: parquet, CSV, or a database URL. Worked mappings, including a
PSP-shaped disputes export: [`examples/`](https://github.com/Thebinary110/Strike-One/blob/main/examples/).

## The terminal UI

Ships bundled in the wheel - `pip install strikeone` is enough (plus a
Node 18+ runtime: your own, or `pip install "strikeone[tui]"` to have
pip manage one):

```bash
strikeone tui --example synthetic
strikeone tui --help          # usage + all keys
strikeone tui --source yourdata.parquet   # uses .strikeone.toml beside it
```

<img src="https://raw.githubusercontent.com/Thebinary110/Strike-One/main/reports/stage6/tui_audit.png" width="820" alt="Strike One TUI, audit panel">

Seven panels (CONNECT, AUDIT, ROUTE, ECONOMICS, STREAM, CASE, AI), fully
keyboard-driven, offline over stdio to the local Python core - and a
an always-visible input box, Claude-Code style - no mode key, just
type and press enter (live suggestions, tab-complete, history, click to
move the cursor):

```
/audit 50            re-run the audit at your real review capacity
/why 11254           explain one decision (AI, citations validated)
/timeline c1097      narrate one fraud case
/compare 21349       blocklist lane vs scorer on one transaction
/evidence why 11254  the raw evidence contract - no model needed
/policy e=0.8 s=0.5  reprice the decision policy
/case <entity>       jump to any case  ·  /provider  ·  /source <path>
/onboard <file>      the full mapping wizard, in-session (label always
                     human-confirmed; esc aborts with nothing written)
/setup ollama <model>            configure the AI provider from inside
```

Anything that isn't a command is a **question**: type "how many fraud
cases are there?" and the model answers from a hashed contract of the
session's own computed numbers - the citation validator still checks
every figure before it prints. Commands themselves never touch the
model: the command line maps 1:1 onto the same deterministic engine
calls the CLI uses. The input line is a real
editor - block cursor, arrow keys, ctrl-a/e/u/w, up/down for history,
paste-safe. Mouse click-to-cursor is opt-in (`mouse on`); by default
your terminal's native text selection and copy/paste work normally.

## The AI layer (optional, off by default)

Narration, not intelligence: the engine makes every decision and computes
every number; a language model only turns finished evidence into
sentences, and **every claim it makes is re-checked against that evidence
before printing** (fail closed — a wrong number is dropped, not printed).
With no provider configured, nothing changes anywhere.

```bash
strikeone ai why 11254      --example synthetic   # explain one decision
strikeone ai timeline c1097 --example synthetic   # narrate one case
strikeone ai compare 21349  --example synthetic   # two systems, one txn
```

What `why` prints, verbatim (local model, nothing installed for the
judge — this exact output is committed under [`examples/ai/`](https://github.com/Thebinary110/Strike-One/blob/main/examples/ai/)):

```text
STRIKE ONE AI  WHY THIS DECISION  (why 11254)
──────────────────────────────────────────────────────────────────────────
  The engine issued a BLOCK decision for this transaction. [F1]
  The transaction was routed to lane 1 via a point-in-time blocklist. [F2]
  The entity's episode state is already flagged. [F3]
  The entity has 1 known prior fraud, exceeding its baseline of 0.0453. [F5]
  The fraud probability is 0.3147, which is higher than its baseline of
      0.0204. [F8]
  The score percentile is 98.7311, significantly above the baseline of
      50.0. [F9]
  The decision results from the entity's flagged status and high fraud
      probability relative to its history.

  citations: 6 of 6 claims validated · evidence sha256:4313fe71c60f
  narrated by: qwen3.6:35b (ollama, local) — every number above was computed
  by the engine and re-checked against the evidence contract before printing
```

How it stays honest:

- **The evidence contract.** Before any model speaks, the engine emits a
  versioned, hashed JSON document (`--show-evidence` prints it) with the
  decision, lane, episode state and named evidence values. The model
  receives exactly this and nothing else — never raw transaction rows,
  never holdout data (asserted by test).
- **The citation validator.** The model must emit structured
  `CLAIM: <id> | <value> | <sentence>` lines. Each cited value is
  re-read from the contract; a mismatch, an unknown id, any number the
  contract does not vouch for, or any decision-bearing word
  (approve/block/step-up/legitimate/fraudulent/…) the cited evidence
  does not itself carry drops the line — digit-free assertions cannot
  smuggle a verdict either. Every output reports its validity rate and
  the evidence hash it narrates.
- **Deterministic routing.** `why`/`timeline`/`compare` map to evidence
  builders in a plain dict; the model never chooses a tool. There is
  deliberately no `/challenge`, `/investigate` or `/simulate` — a model
  second-guessing a deterministic decision is an unmeasured second fraud
  model, and this repo does not ship one.
- **Provider independence is a test, not a demo.** A pytest harness runs
  one fixed evidence contract through pinned model slugs via a single
  OpenRouter key plus local Ollama and asserts the validator passes for
  every one. Recorded run: **citation validity 100% of 40 claims across
  6 models from 6 families**
  ([`examples/ai/independence_run.txt`](https://github.com/Thebinary110/Strike-One/blob/main/examples/ai/independence_run.txt)).
  It needs `OPENROUTER_API_KEY` and skips cleanly without it.

Providers — one interface, two adapters:

| provider | config | evidence path |
|---|---|---|
| Ollama (default suggestion) | `strikeone ai setup --provider ollama --model <name>` | never leaves the machine |
| any OpenAI-compatible endpoint (OpenAI, OpenRouter, Ollama Cloud, custom) | `--provider openai-compatible --base-url <url> --model <slug> --api-key-env <NAME>` | this machine → endpoint (→ the routed provider, if an aggregator) |

Credentials are **env vars only** — the config stores the variable's
NAME, a test asserts no writer can persist a value from any `*KEY*` /
`*TOKEN*` env var, and `strikeone ai setup` never prompts for a secret
(a masked prompt still lands in scrollback and recordings).
`strikeone ai provider` prints the full chain, including the two-party
path through an aggregator. On OpenRouter specifically: its account
settings control which underlying providers may retain or train on
requests, but its own logging practices are separate from the
providers' — check their privacy-and-logging docs for your account
before sending anything sensitive.

The LLM never computes or alters risk, selects thresholds, chooses
actions, touches the holdout, modifies any metric, or produces any
number reported in this repo's results.

## How it works

1. Your rows are sorted chronologically; a fraud **case** is one
   entity's run of fraud, and only its **first labelled transaction** was
   ever catchable before the entity was known.
2. A point-in-time blocklist is simulated from your labels and your
   stated label delay: what a lookup table would already have known.
3. Every alert your scorer would raise, at your review capacity, is
   classified: first-hit catch, later attempt (blocklist-coverable),
   or flagged good customer.
4. All comparisons are budget-matched; nothing is compared at different
   alert counts.

## How this maps to the track brief

| the track asks for | where it is |
|---|---|
| pick one class of loss | card-not-present fraud chargebacks (IEEE-CIS) |
| a working detector | the reference detector A2, frozen by SHA-256 before the holdout opened (`reports/stage4/shipped_system_frozen.json`, `b632a136…`) |
| an automated responder | the approve / step-up / block policy (`strikeone policy`), plus the blocklist lane (`strikeone route`) |
| measured precision/recall | per review budget, on the sealed holdout: `reports/stage7/`, C1–C12 in `canonical_comparisons.md` |
| a held-out evaluation set | days 151–182, SHA-256-sealed; **two accesses, each pre-registered and logged** (`reports/holdout_access.log`) |
| the cost of false positives | first-class: FP counts at every budget, lane-1 legitimate blocks counted, declared economic ranges with a published sensitivity grid |
| defense only | the tool evaluates and routes; nothing here probes, evades, or attacks anything |

## Limitations

- The included IEEE-CIS run is a **reference detector, not a deployable
  model on your traffic**; nothing here applies our weights to your
  transactions. It exists so the evaluation has a measured, frozen,
  reproducible subject — swap in your own scorer for real decisions.
- First-hit counts on a standalone export are an **upper bound** (window
  truncation); `--history` tightens them. Label maturity you declare is
  taken at face value; slower maturity shrinks every blocklist figure.
- The economics are **declared ranges, not your economics**; the policy
  refuses uncalibrated probabilities rather than calibrating on your
  evaluation data. Liability shift is a parameter (`s`), default 0; in
  India, RBI's authentication mandate makes step-up the norm rather than
  a liability lever — stated, not modelled.
- If your labels are entity-independent (stickiness ≈ 1), first-hit
  metrics add nothing over ordinary recall — the tool detects this and
  says so rather than printing an impressive number.

## Honest by design

- Every output states its assumptions and its blind spots (label
  maturity, entity-key resolution, window truncation) next to the
  numbers, and `check` refuses data it cannot audit correctly.
- The study behind the method: a sealed holdout with **two logged
  accesses, each against a pre-registered plan committed beforehand**
  — including the predictions that missed, self-caught bugs documented,
  negative results published. Read [`FINDINGS.md`](https://github.com/Thebinary110/Strike-One/blob/main/FINDINGS.md) and
  [`reports/`](https://github.com/Thebinary110/Strike-One/blob/main/reports/).

## Data and license

The worked study uses the public IEEE-CIS dataset (Vesta / Kaggle
2019); nothing from it is committed to this repo - scripts download and
checksum-verify it. Fonts in the TUI-adjacent extras are Fontshare
(ITF FFL, licences committed). Code: Apache-2.0.
