# Strike One

Bring-your-own-scorer fraud routing and the corrected evaluation, as an
installable package with a terminal UI. Built for the Razorpay AI
Buildathon (AI Risk Manager track). Strictly defense-only.

**We ship the method and the measurement. You bring the scorer. The
included IEEE-CIS run is a worked example, not a deployable model** — a
model trained on Vesta's anonymised US data does not transfer to your
production traffic, and we will not pretend otherwise. What does
transfer: the blocklist routing lane, and an audit nobody can get today
without writing what we already wrote.

**Your data never leaves the machine.** No telemetry, no network calls,
anywhere in the package.

## Quickstart

```bash
pip install -e .                      # or: uv sync
strikeone check --example ieee-cis    # validate the worked example
strikeone audit --example ieee-cis    # the corrected evaluation, live
strikeone tui                         # the terminal UI (Node 18+)
```

No pipeline outputs built yet? `--example synthetic` runs instantly on
generated data (clearly labelled as such; the repo never vendors dataset
rows). Against your own data, no code required:

```bash
strikeone audit yourdata.parquet \
  --map transaction_id=txn_id --map timestamp=created_at \
  --map amount=amount_inr --map entity=card_hash+email_hash \
  --map label=is_chargeback --delay 30 --save-config
```

`strikeone audit` answers, for YOUR labelled data: how many of your fraud
cases are stopped at the first attempt (vs what your headline AP/recall
says), what share of your correct alerts land on entities a blocklist
already knows, and how much of your headline metric a blocklist alone
recovers. `strikeone route` wraps whatever scorer you already run with
the two-lane routing and measures the lift. `strikeone policy` turns
declared-range economics into {approve, step-up, block} recommendations.
Mapping examples, including a PSP-shaped disputes export: `examples/`.

Library API mirrors the CLI: `from strikeone import audit, route, policy`
(modules `strikeone.audit`, `strikeone.route`, `strikeone.policy_engine`).

## The claim

On the most widely used **public** benchmark for card fraud, the standard
evaluation cannot distinguish *preventing* fraud from *remembering* it —
and it systematically prefers the model that remembers. **At a 500-alert
budget, the higher-AP model catches 2.7× fewer first strikes (7.9% vs
21.0% first-strike recall; friction efficiency 0.16 vs 0.44).** A
scoreless blocklist reaches 54% transaction precision while preventing
nothing; adding the entity-history features everyone adds buys +0.17 AP
while *reducing* first-strike recall with a confidence interval that
excludes zero. Every piece is measured under a chronological protocol,
paired-tested, key-sensitivity-checked — and re-confirmed on a sealed
out-of-time holdout opened exactly once against a pre-registered plan.

Two further named results. **Money is not an escape hatch:** realized
cost computed on propagated labels *is* amount-weighted AP — a team that
tries to dodge the metric distortion by "just measuring money" inherits
it intact; priced with episode-aware accounting, the +0.17 AP gap is
worth ±0.03–0.14% of processed volume with a sign that flips across a
reasonable cost grid — economically negligible at the unconstrained cost
optimum, decisive under the capacity constraints every real risk team
operates under. **Routing inoculation:** an explicit blocklist lane lifts
the headline model's own tight-budget first-strike recall 0.079 → 0.246
(3.1× on validation; 2.32× on the holdout, as pre-registered) without
touching the model — the architecture protects any scorer.

And the yardstick chose the better *system*, not just the better score:
because the corrected metric selected a scorer with **no entity
aggregates**, the shipped system needs **no online feature store — its
total online state is one blocklist key-value set — and scores at 7.84 ms
p99 on a laptop CPU** (577k rows/s batched). The distortion was pushing
toward a heavier, statefuller system that prevented less; **the honest
yardstick picked the simpler, faster, cheaper-to-operate one.**

**Generalisation bridge — hypothesis, not measurement:** label
propagation is not a quirk of this dataset's annotation; it is what any
chargeback-derived label set looks like, because real blocklists work the
same way. Any team training on chargeback-derived labels against a
transaction-level metric is exposed to the same distortion. We measured
it on one public benchmark; we did not measure it on anyone's production
data, and we say so.

## The mechanism: how the labels were made

The dataset's host labeled the reported chargeback *and every later
transaction linked to the same user account, email address, or billing
address* as fraud; anything unreported for 120 days is labeled
legitimate. The positive class therefore mixes "the moment an episode
started" (a **first strike** — catching it prevents loss) with
"transactions a blocklist would have caught for free" (**propagated** —
catching them prevents nothing). Transaction-level metrics credit both
equally, so they reward remembering. Every operational magnitude we quote
is dataset-specific; the *mechanism* is what we claim generalises (as a
hypothesis, above).

## The self-carved holdout, and why

The official `test.csv` labels were never released, so we carve a
chronological holdout (days 151–182) from the training file, seal it in
code (SHA-256 pinned, loadable only through an access-logged unseal call),
and open it **exactly once**, at the end, against a pre-registered
analysis plan. `reports/holdout_access.log` contains **exactly one
entry** — timestamped, hash-verified, with the pre-registration commit in
its stated reason. A clean-clone rebuild reproduces the sealed file
byte-identically.

## Bugs our own checks caught

Two independent self-catches, which we consider the strongest integrity
signal in this repo:

1. **A pandas-3 behaviour change silently nulled the entity id on 11.4%
   of rows**, and each null-entity fraud was counted as its own "first
   strike" — **inflating our own headline metric by ~55%** (1,610
   apparent first-strike episodes; 1,040 real). Caught by the Stage 3
   fragmentation audit — a check built for a *different* failure mode —
   because the pipeline audits its own central number. Fixed,
   regression-tested (`episode_roles` now refuses null ids), every
   affected number rebuilt with correction banners; originals preserved
   in git history.
2. **A replay-preparation refit briefly trained the lane-2 model with the
   bookkeeping `uid` column as a 43,000-category feature** (scores
   diverged from the frozen system by up to 0.67). Caught immediately by
   the cache-match assertion that requires any rescoring to reproduce the
   frozen artifact's outputs; fixed by scoring only with the
   hash-verified frozen booster.

A submission whose checks have never fired is a submission whose checks
were never tested. Ours fired twice, on our own headline numbers, before
any external reader saw them.

## The pre-registration, and whether it held

Predicted ranges, an eight-item analysis plan (exact figures, order, and
operating points), and the two-number reporting policy were committed
**before** the seal broke (`reports/holdout_prediction.md`). Scorecard:
**6 hits, 3 misses — misses first**:

- **Primary AP missed high** (0.532 vs predicted [0.32, 0.48]): the
  frozen model aged far better than our decay extrapolation. Integrity
  checks (hash, exact counts, feature-list asserts) preceded belief; no
  unregistered diagnostics were run.
- **The distortion did not weaken** (B−A = +0.177 vs predicted
  +0.06…+0.14) — because its input variable didn't move: the propagated
  share of positives stayed at 62.7% (predicted to fall), as propagation
  regenerates *within* the window. The forecast of the input was wrong;
  **the mechanism — distortion scales with propagated share — behaved
  exactly as claimed** (share flat ⇒ distortion flat, +0.174 → +0.177).
- Hits: primary AUC, secondary AP and AUC, routing ratio (2.32× in
  [1.5, 2.8]), lane-1 row and positive shares.

Full scorecard and discussion: `reports/STAGE_7.md`.

## Assumption ranges, and the remaining caveats

- **Every economic figure is an assumption range, not a fact.** We are
  not Razorpay and do not know their economics. Cost parameters are
  declared ranges (m ∈ [0.05, 0.25], a ∈ [0.05, 0.20], e ∈ [0.60, 0.95],
  c_h ∈ [15, 60] amount-units) with a published 81-corner sensitivity
  grid and its vanishing corner named. No single rupee figure is stated
  as fact anywhere.
- **The entity key is a proxy** for the host's true propagation key;
  episode results are reported under alternate keys with the sensitivity
  quantified (the core claim is key-robust; one secondary claim is
  key-dependent and flagged).
- **Measured precision is a lower bound** — the host acknowledges
  unreported fraud is labeled legitimate, and our hand-inspected top
  "false positives" include same-entity twins of labeled fraud.
- **The 7-day label-availability delay is optimistic** (real chargebacks
  mature over ~30–120 days), so every label-derived-feature gain we
  report is an upper bound on its production value.

## Results — the holdout, opened once

Primary = the frozen day-112 pipeline; secondary = the same recipe refit
through day 147 with nested calibration (never on the holdout). Holdout:
92,427 rows / 32 days / 3,213 positives / **1,198 first-strike episodes**.

| Model | AP | ROC-AUC |
|---|---|---|
| Primary A (frozen) | 0.5319 [0.5167, 0.5504] | 0.9033 [0.8972, 0.9099] |
| Primary B (headline pick) | 0.7088 | 0.9544¹ |
| Secondary A (refit d147) | 0.6001 [0.5843, 0.6176] | 0.9239 |

¹ Above the competition winner's private 0.9459 — not a leak: B holds an
information source no competition entrant had (labels ≥7 days old inside
the evaluation window). A blocklist-echo model beating the competition
ceiling *is the thesis*. The sanity ceiling applies to
competition-comparable models; A sits at 0.9033.

**The inversion survives out-of-time** (at the blocklist's natural
N=1,775): blocklist 49.8% precision / **0** first strikes; A 69.9% / 566;
B **89.1%** / 442. Precision rises as prevention falls.

**The counters (100 alerts/day, 3,200 total)** — shipped two-lane+A2:
**698 of 1,198 episodes stopped at strike one** against **692 alerts
spent on already-known-bad entities** (single-lane B: 643 and 1,425),
with 1,775 known-bad entities handled by the blocklist lane at zero alert
cost (891 legitimate transactions blocked by that standing policy —
counted, shown, future work). **B−A first-strike recall on holdout:
−0.0192 [−0.0326, −0.0052]** — the headline winner is again significantly
worse at prevention. Retraining cadence is worth **+0.068 AP**
(primary → secondary). The console reproduces every counter from
`holdout_replay.parquet` — the same swapped-parquet path proven in
Stage 6.

## Why no graph model

The plan reserved time for a graph-feature ablation. We skipped it — not
on a prediction, but on three measurements already in our reports:

1. **The outcome space collapsed.** With the blocklist lane on, two very
   different scorers (A2 and the label-feature-heavy B) sit within ±0.01
   first-strike recall of each other across the entire capacity range.
   An experiment in that space has no power to resolve a third scorer.
2. **98.8% of first strikes are on entities never seen before** (1,027 of
   1,040 validation episodes). A graph over past edges has no
   neighbourhood exactly where all the prevention lives.
3. **Behavioural history over those same edges measured actively harmful
   where it is populated**: −0.0657 AP within known entities (CI
   excluding zero), because there the label is determined by propagation
   history, not behaviour.

Showing this reasoning beats manufacturing a null we can already derive.

## Reproduce the worked example

```bash
uv sync                          # pinned environment (uv.lock)
bash scripts/download_data.sh    # fetch + checksum-verify the public dataset
uv run pytest                    # unit tests (metrics, episodes, seal, console)
uv run python scripts/stage0_build.py        # ingest, split, seal holdout
uv run python scripts/stage1_baseline_a.py   # Baseline A (frozen)
uv run python scripts/stage1_leak_table.py   # the 2x2 leakage table
uv run python scripts/stage2_baseline_b.py   # entity features + ablations
uv run python scripts/stage2_uid_family.py   # UID-family experiment
uv run python scripts/stage3_episode_analysis.py  # episode/friction tables
uv run python scripts/stage4_lane2.py        # lane-2 retrain (A2)
uv run python scripts/stage4_policy.py       # decision engine + freeze
uv run python scripts/stage4_episode_cost.py # episode-aware pricing
uv run python scripts/stage6_prepare_replay.py    # console replay file
uv run python -m strikeone.console           # -> http://127.0.0.1:8777
# Stage 7 (already executed once; the run script refuses a second unseal):
#   uv run python scripts/stage7_prepare.py
#   uv run python scripts/stage7_run.py
```

All randomness is seeded (`strikeone.config.SEED`). Runs on a laptop CPU;
no cloud, no GPU. Clean-clone reproduction is verified through
`stage0_build` (byte-identical holdout hash) and the full test suite.
The optional web console (`strikeone console`, a self-contained stdlib
server) remains as an extra surface; the package and the TUI are the
product.

## Data: source, faithfulness, licensing

**Dataset.** IEEE-CIS Fraud Detection — real-world e-commerce transactions
provided by Vesta Corporation for the 2019 Kaggle competition run with the
IEEE Computational Intelligence Society
(https://www.kaggle.com/c/ieee-fraud-detection). The dataset is also
archived on IEEE DataPort. Only the two *training* files are used; the
official test set's labels were never released and this project never
touches it.

**Two ways to fetch it.**
1. `scripts/download_data.sh` (default) — pulls the two files from an
   ungated public mirror, so a clean clone reproduces with one command and
   no Kaggle account.
2. Canonical, attributed source — `kaggle competitions download -c
   ieee-fraud-detection` (requires a Kaggle account that has joined the
   competition), then place `train_transaction.csv` and
   `train_identity.csv` in `data/raw/`.

**Faithfulness.** Whichever path you use, ingestion verifies three
independent fingerprints of the official data, and the download script
additionally checks pinned SHA-256s: exact shapes (590,540×394 and
144,233×41), exact positive count (20,663), and exact max `TransactionDT`
(15,811,131 s = day 182.999). A subtly different mirror would need to match
all three simultaneously to slip through.

**Licensing.** The data was released publicly by Vesta for the competition
and its use here is non-commercial research/education under the
competition's data-use terms. The data is **not vendored** in this
repository — no row of it is committed; scripts fetch it from public
hosting and verify integrity.

## Layout

- `src/strikeone/` — the package: contract + mapping (`contract.py`),
  `audit`, `route`, `policy_engine`, `cli`, `rpc` (the TUI's backend),
  plus the evaluation core (metrics, episodes, entity, seal) and the
  optional web console; see `ARCHITECTURE.md`
- `tui/` — the Ink terminal UI (TypeScript; a surface, never a dependency
  of the core)
- `examples/` — mapping examples: IEEE-CIS and a PSP-shaped disputes
  export
- `scripts/` — one entry point per pipeline stage (the worked example)
- `reports/STAGE_N.md` — per-stage findings, written for a skeptical
  reader; `reports/holdout_prediction.md` — the pre-registration;
  `reports/holdout_access.log` — the seal's one entry
- `PROPOSALS.md` — judgment calls outside the build brief
