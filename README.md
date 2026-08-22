# Strike One

An episode-aware card-not-present fraud risk engine, built on the IEEE-CIS
Fraud Detection dataset for the Razorpay AI Buildathon (AI Risk Manager
track). Strictly defense-only.

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
paired-tested, and key-sensitivity-checked.

Two further named results. **Money is not an escape hatch:** realized
cost computed on propagated labels *is* amount-weighted AP — a team that
tries to dodge the metric distortion by "just measuring money" inherits
it intact; priced with episode-aware accounting, the +0.17 AP gap is
worth ±0.03–0.14% of processed volume with a sign that flips across a
reasonable cost grid — economically negligible at the unconstrained cost
optimum, decisive under the capacity constraints every real risk team
operates under. **Routing inoculation:** an explicit blocklist lane lifts
the headline model's own tight-budget first-strike recall 0.079 → 0.246
(3.1×) without touching the model — the architecture protects any scorer.

**Generalisation bridge — hypothesis, not measurement:** label
propagation is not a quirk of this dataset's annotation; it is what any
chargeback-derived label set looks like, because real blocklists work the
same way. Any team training on chargeback-derived labels against a
transaction-level metric is exposed to the same distortion. We measured
it on one public benchmark; we did not measure it on anyone's production
data, and we say so.

## The audit that validates the method

Midway through, a check built to rule out one failure mode (entity
fragmentation) caught a different one: a pandas-3 behaviour change had
silently nulled the entity id on 11.4% of rows, and each null-entity
fraud was being counted as its own "first strike" — **inflating our own
headline metric by ~55%** (1,610 apparent first-strike episodes; 1,040
real ones). The bug was found *because* the pipeline audits its own
central number, fixed, regression-tested, and every affected result was
rebuilt and corrected in place (`reports/STAGE_2.md` carries the banner;
git history preserves the originals). We keep this story at the top
because it is the strongest evidence we can offer that the numbers below
survive hostile reading.

## Read the limitations first

This project's claims are only as strong as these caveats, so they come
before any result:

1. **The labels are propagated, not per-transaction.** The dataset's host
   labeled the reported chargeback *and every later transaction linked to
   the same user account, email address, or billing address* as fraud. The
   positive class therefore mixes "the moment an episode started" with
   "transactions a blocklist would have caught for free". Our central claim
   is about the **metric distortion** this creates in model selection;
   any operational magnitude we quote is dataset-specific.
2. **Our held-out test set is self-carved.** The official `test.csv` labels
   were never released, so we carve a chronological holdout (days 151–182)
   from the training file, seal it in code (SHA-256 pinned, access-logged),
   and open it exactly once. See `reports/holdout_access.log` — it should
   contain exactly one entry.
3. **Every economic figure is an assumption range, not a fact.** We are not
   Razorpay and do not know their cost structure. Cost parameters are
   declared ranges with a published sensitivity grid; no single rupee figure
   is stated as fact.
4. **The entity key is a proxy.** The published UID reconstruction
   approximates the host's true propagation key; episode results are
   reported under alternate keys with the sensitivity quantified.
5. **Measured precision is a lower bound.** The host acknowledges unreported
   fraud is labeled legitimate.

## Reproduce

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
```

All randomness is seeded (`strikeone.config.SEED`). Runs on a laptop CPU; no
cloud, no GPU. The console is self-contained (stdlib server, no auth, no
database); its every number is computed from the replay file and the frozen
Stage 4 config — swap `--data` to re-point it (Stage 7 does exactly that).

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

- `src/strikeone/` — library (data, splits, seal, metrics, episodes)
- `scripts/` — stage entry points
- `reports/STAGE_N.md` — per-stage findings, written for a skeptical reader
- `PROPOSALS.md` — judgment calls outside the build brief
