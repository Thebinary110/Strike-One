# Findings: the research behind Strike One

The full study lives in `reports/` (one report per stage, every
correction banner intact, originals in git history). This file is the
narrative summary, moved out of the README to keep that page simple.

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
out-of-time holdout whose every access (two, both against plans
committed beforehand) is logged.

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
touching the model. The lane is scorer-agnostic by construction; the lift
itself is measured per scorer, and the tool reports it honestly when a
lane adds nothing.

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
and open it only against pre-registered analysis plans committed before
each unsealing. `reports/holdout_access.log` contains **exactly two
entries** — timestamped, hash-verified, each with its pre-registration
commit in the stated reason: the Stage-7 final evaluation (188b471) and
a second access for baselines and robustness checks (67d35f7,
`reports/stage8/SECOND_ACCESS.md`) that could not change the frozen
system, only report on it. A clean-clone rebuild reproduces the sealed
file byte-identically.

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

A **second access** (baselines and robustness checks, pre-registered at
67d35f7) has its own scorecard: no-reversal and random-floor predictions
hit; two magnitude predictions missed — one against us (rank-by-amount is
a far stronger loss-weighted baseline than we called, see Results), one
for us (the rebuilt cost edge exceeded its predicted band). Full details:
`reports/stage8/SECOND_ACCESS.md`.

## Assumption ranges, and the remaining caveats

- **Every economic figure is an assumption range, not a fact.** We are
  not Razorpay and do not know their economics. Cost parameters are
  declared ranges (m ∈ [0.05, 0.25], a ∈ [0.05, 0.20], e ∈ [0.2, 0.95] —
  the e floor was widened from 0.6 after a reviewer challenged it,
  post-results and stated as such — c_h ∈ [15, 60] amount-units,
  liability shift s ∈ [0, 1], default 0) with a published sensitivity
  grid and its weakest corner named. The cost policy's edge over a fixed
  threshold was rebuilt out-of-sample after review (the original
  same-data "81/81" was withdrawn as near-tautological — Cawley &
  Talbot, JMLR 2010): validation-tuned threshold vs validation-fitted
  policy, both scored on the sealed holdout, per-corner bootstrap CIs —
  **81 of 81 corners, median edge +14.4% of approve-all cost** — and
  then decomposed: that advantage is **mostly the value of having a
  step-up action at all** (amount-aware vs amount-blind three-action:
  55/81, central gap 0.04% — the cost arithmetic itself is worth
  approximately nothing). The extended e sweep names the breaking
  point: unanimity holds down to **e = 0.5** and fails corner-by-corner
  below it; the median edge never goes negative in [0.2, 0.95]. All
  under the stated counterfactual assumption (a blocked fraud is fully
  avoided; a stepped-up one avoided with probability e). No single
  rupee figure is stated as fact anywhere.
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

## Results — the holdout

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
(primary → secondary). The replay tooling reproduces every counter from
`holdout_replay.parquet` — the same swapped-parquet path proven in
Stage 6.

**Baselines nobody can skip (second access).** At the same 3,200 alerts:
a random ranker sits at the budget share on everything (~3–4%). On the
headline metric — unweighted first-hit recall — a rank-by-amount sort is
nowhere: **5.3% of cases at 5.5% precision (3,023 flagged good
customers) vs the shipped 58.3% at 45.7%**. On *loss-weighted* first-hit
recall, though, the same no-model sort **reaches 0.3447, 73% of the
shipped 0.4733**; we predicted 0.05–0.20 and a ≥2× margin, and that
prediction missed. Per the pre-registration the finding is reported, not
buried — and it is a finding about metric design as much as about this
system: any loss-weighted metric partially rewards amount-ranking by
construction (its numerator is denominated in the ranking key). So
loss-weighted figures are secondary here and never quoted without the
rank-by-amount row beside them. The shipped system stays ahead of it at
every budget (1.26–1.83×). `reports/stage8/baselines_kcurve.csv`.

**The conclusion survives slower labels (second access).** Rebuilding
the evaluation-side blocklist at 1/3/7/14/30-day maturity: the shipped
system's first-hit-recall edge over single-lane B stays positive with
CIs excluding zero at every delay — +0.0543 at 1 day, **+0.0434 at 30
days**. No reversal; no boundary to name. (Scope limit: B's
label-derived features remain trained at 7 days; a fully consistent
sweep would retrain per delay.) `reports/stage8/maturity_sweep.csv`.

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
uv run pytest                    # unit tests (contract, audit, metrics, seal)
uv run python scripts/stage0_build.py        # ingest, split, seal holdout
uv run python scripts/stage1_baseline_a.py   # Baseline A (frozen)
uv run python scripts/stage1_leak_table.py   # the 2x2 leakage table
uv run python scripts/stage2_baseline_b.py   # entity features + ablations
uv run python scripts/stage2_uid_family.py   # UID-family experiment
uv run python scripts/stage3_episode_analysis.py  # episode/friction tables
uv run python scripts/stage4_lane2.py        # lane-2 retrain (A2)
uv run python scripts/stage4_policy.py       # decision engine + freeze
uv run python scripts/stage4_episode_cost.py # episode-aware pricing
uv run python scripts/stage6_prepare_replay.py    # worked-example replay file
# Stage 7 (already executed once; the run script refuses a second unseal):
#   uv run python scripts/stage7_prepare.py
#   uv run python scripts/stage7_run.py
# Second pre-registered access (already executed; refuses to re-run —
# it asserts the log holds exactly one entry before, two after):
#   uv run python scripts/stage8_access2.py
```

All randomness is seeded (`strikeone.config.SEED`). Runs on a laptop CPU;
no cloud, no GPU. Clean-clone reproduction is verified through
`stage0_build` (byte-identical holdout hash) and the full test suite.

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
