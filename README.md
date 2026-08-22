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

## Layout

- `src/strikeone/` — library (data, splits, seal, metrics, episodes)
- `scripts/` — stage entry points
- `reports/STAGE_N.md` — per-stage findings, written for a skeptical reader
- `PROPOSALS.md` — judgment calls outside the build brief
