<div align="center">

# Strike One

**A reference fraud detector, measured on a sealed holdout — and the
episode-aware evaluation that selected it. Swap in your own scorer.**

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB)
![License](https://img.shields.io/badge/license-Apache--2.0-green)
![Tests](https://img.shields.io/badge/tests-58%20passing-brightgreen)
![Offline](https://img.shields.io/badge/network%20calls-zero-black)

</div>

Fraud labels propagate: once a fraudster is confirmed, all their later
attempts get labelled fraud too. Standard metrics credit a model for
re-catching them — alerts a standing blocklist would also have covered.
Strike One measures that gap on **your** data, with **your** model, and
ships the reference detector the corrected evaluation selected.

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
literature we run backwards: [`reports/PRIOR_ART.md`](reports/PRIOR_ART.md).

## Install

```bash
git clone https://github.com/Thebinary110/Strike-One && cd Strike-One
pip install -e .          # or: uv sync
```

The TUI additionally needs Node 18+: `cd tui && npm install && npx tsc`.

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

The study behind the tool (full narrative: [`FINDINGS.md`](FINDINGS.md),
every figure: [`reports/stage7/canonical_comparisons.md`](reports/stage7/canonical_comparisons.md)):

- **The distortion is real and selects the wrong model.** Adding the
  entity-history features everyone adds buys +0.17 AP while *reducing*
  first-hit recall (−0.019, CI excluding zero, holdout).
- **The conclusion survives slower labels.** Rebuilding the evaluation
  blocklist at 1–30-day label maturity, the shipped system's first-hit
  edge stays positive with CIs excluding zero at every delay (+0.054 at
  1 day, +0.043 at 30). No reversal; no boundary to name.
- **A baseline we could not skip, reported because it surprised us:**
  ranking by amount alone — no model — reaches **0.345 loss-weighted
  first-hit recall at 100 reviews/day, 73% of our 0.473**. We
  pre-registered a prediction that it would land in 0.05–0.20; it did
  not. It never beats the shipped system at any budget, and it is
  unusable on every unweighted metric (5.3% of cases caught, 5.5%
  precision), but if loss-weighted coverage were your only objective, a
  sort-by-amount gets most of the way on this data.
- **Costs, out-of-sample:** the three-action policy beats a
  validation-tuned fixed threshold on the holdout in **81 of 81 declared
  economic corners** (per-corner bootstrap CIs excluding zero), median
  edge +14.4% of approve-all cost, IQR [+9.3%, +20.5%], weakest corner
  +3.4% — under the stated counterfactual that a blocked fraud is fully
  avoided and a stepped-up one avoided with probability e (the e and s
  grid dimensions are that assumption's sensitivity). An earlier
  same-data version of this claim was withdrawn as near-tautological
  (Cawley & Talbot, JMLR 2010); this is the rebuilt one.

## Use it on your data - no code

Map your columns once, then every command works:

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
PSP-shaped disputes export: [`examples/`](examples/).

## The terminal UI

```bash
strikeone tui --help          # usage + all keys
strikeone tui --example ieee-cis
```

<img src="reports/stage6/tui_audit.png" width="820" alt="Strike One TUI, audit panel">

Six panels (CONNECT, AUDIT, ROUTE, ECONOMICS, STREAM, CASE), fully
keyboard-driven, runs offline over stdio to the local Python core.

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
  negative results published. Read [`FINDINGS.md`](FINDINGS.md) and
  [`reports/`](reports/).

## Data and license

The worked study uses the public IEEE-CIS dataset (Vesta / Kaggle
2019); nothing from it is committed to this repo - scripts download and
checksum-verify it. Fonts in the TUI-adjacent extras are Fontshare
(ITF FFL, licences committed). Code: Apache-2.0.
