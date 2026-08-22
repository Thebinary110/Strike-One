# Strike One

An episode-aware card-not-present fraud risk engine, built on the IEEE-CIS
Fraud Detection dataset for the Razorpay AI Buildathon (AI Risk Manager
track). Strictly defense-only.

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
uv run pytest                    # metric unit tests
uv run python scripts/stage0_build.py   # ingest, split, seal holdout
```

All randomness is seeded (`strikeone.config.SEED`). Runs on a laptop CPU; no
cloud, no GPU.

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
