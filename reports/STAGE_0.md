# Stage 0 — Scaffold, data, split, metrics

## What was done

1. **Data ingested and verified.** Two raw files fetched from an ungated
   public mirror of the Kaggle competition data (see PROPOSALS.md P-001),
   SHA-256s pinned in `data/raw_checksums.sha256`:
   - `train_transaction.csv`: **590,540 × 394** (matches expectation exactly)
   - `train_identity.csv`: **144,233 × 41** (matches exactly)
   - `TransactionID` unique in both; every identity row joins a transaction.
   - Overall fraud rate **3.50%** (20,663 positives).
   - The official test set was not downloaded and will never be (its labels
     do not exist; brief invariant 5).
2. **Day index.** `TransactionDT` runs 86,400–15,811,131 seconds, i.e. days
   **1.000–182.999**. All work is in day indices; no calendar dates anywhere.
   Slice membership uses `day_idx = floor(day)`, inclusive bounds; the build
   asserts the slices partition all 590,540 rows.
3. **Chronological split** built as proposed in the brief, after checking
   the data for better cut points (it didn't suggest any — see below):

   | Slice | Days | Rows | Positives | Fraud rate | Amount sum | ID coverage | Amt median | Amt mean | Amt p95 |
   |---|---|---:|---:|---:|---:|---:|---:|---:|---:|
   | Train | 1–112 | 389,523 | 13,350 | 3.43% | 52,432,828 | 26.7% | 69.00 | 134.61 | 445.00 |
   | Delay gap | 113–119 | 21,078 | 1,069 | 5.07% | 2,807,307 | 24.8% | 65.98 | 133.19 | 425.08 |
   | Validation | 120–147 | 79,954 | 2,810 | 3.51% | 10,788,560 | 17.7% | 67.95 | 134.93 | 441.00 |
   | Blind gap | 148–150 | 7,558 | 221 | 2.92% | 983,656 | 17.6% | 67.95 | 130.15 | 404.96 |
   | **Holdout** | **151–182** | **92,427** | **3,213** | **3.48%** | 12,726,594 | 21.0% | 68.50 | 137.69 | 445.00 |

   Descriptive columns (identity coverage, amount quantiles) are computed at
   build time from the raw stream, label-free; the sealed parquet content is
   untouched (hash unchanged after this addition).

   - **Identity-join coverage drifts materially: 26.7% (train) → 17.7%
     (val) → 21.0% (holdout).** Every device-keyed feature therefore
     carries a built-in covariate shift between train and evaluation
     periods — and a *different* shift for val than for holdout. Recorded
     here so later stages read device-feature effects with that lens.
   - **TransactionAmt is stable across slices** (median 65.98–69.00, mean
     130–138, p95 405–445), so the Stage 4 savings figure is not silently
     moved by an amount shift between fitting and evaluation periods.
   - **TransactionID is monotonic in TransactionDT** — it is a pure time
     proxy and goes on the permanent feature-exclusion list.

4. **Holdout sealed in code.** Days 151–182 written to their own parquet;
   SHA-256 committed:
   `e053295839390770dd8f4ecaf4214016982830e898fea7c4738587f5db12f499`.
   `strikeone.seal.load_holdout()` is the only sanctioned reader: it raises
   unless `unseal=True` **and** a non-empty reason is passed, verifies the
   hash before returning rows, and appends a timestamped entry to the
   committed `reports/holdout_access.log` (currently **empty — zero
   accesses**). Reproducibility verified: a full rebuild from raw CSVs
   produced a byte-identical file (same hash). Tampering with the file or
   rebuilding different content raises. All behaviors unit-tested.
5. **Metrics module built and unit-tested** (22 tests, all passing, each
   against hand-computed tiny examples):
   - Headline: average precision, PR curve, ROC-AUC.
   - Card Precision@k (per-day card ranking, Fraud Detection Handbook
     convention).
   - Cost model: realized cost, expected-cost matrix (approve / step-up /
     block, Elkan-style), savings vs the cheaper of approve-all/block-all.
   - Episode metrics (Stage 3 definitions): episode roles (legit / first
     strike / propagated), friction accounting (first-strike catches,
     redundant, false positives), friction efficiency, redundancy rate,
     first-strike recall, loss-weighted first-strike recall, plus a
     sub-count of false positives landing on already-flagged entities.
   - Bootstrap CI (row- and group/entity-resampled) and paired bootstrap
     for model deltas, both deterministic under a seed.

## Decisions taken

- **Split boundaries kept as proposed, on evidence.** Weekly profile of
  days 1–150: the only regime shift is days ~1–28 (volume 27–36k/week vs
  ~19–24k afterwards, with a *lower* fraud rate, 2.1–2.9% vs ~3.3–4.4%) —
  it lies entirely inside train. Daily fraud rate around days 105–125 and
  140–150 fluctuates without a structural break at our cut points.
- **Modeling file excludes holdout days entirely.**
  `data/processed/modeling.parquet` holds days 1–150 only; holdout rows
  exist only in the sealed file.
- Fallback and key decisions that belong to later stages (UID fallback for
  null `addr1`/`D1`, censoring of episodes that straddle the holdout
  boundary) were deliberately not taken yet.

## Surprises / notes for the skeptical reader

- **The delay gap (days 113–119) is the highest-fraud-rate week in the
  modeling range: 5.07%** vs 3.4–3.5% for its neighbours (driven by days
  114–117, peaking at 6.4% on day 117). It is discarded — never fitted or
  evaluated on — so the *evaluation* is unbiased. But it is not inert for
  features: under the 7-day label-availability rule, a validation
  transaction on day 120 computes label-derived entity risk features from a
  lookback ending on day 113 — squarely inside the 5.07% week, centred on
  the 6.4% peak — while training rows never see a lookback that dense.
  Early-validation risk features may therefore be displaced upward, and
  Stage 4's cost argument rests on probabilities *calibrated on
  validation*. **Flagged as a Stage 2 check:** once the label-derived risk
  features exist, plot their distribution by day across validation; if days
  120–127 are displaced, either drop that week from the calibration fit or
  move the gap — and say which was done.
- **The blind gap is belt-and-braces, not a guarantee.** Its 3 days are
  thinner than the official competition's ~30-day train/test separation,
  and D-column timedeltas reach back much further than 3 days, so the gap
  alone does not prevent features from bridging the holdout boundary. The
  real defence is point-in-time feature construction; the gap only blunts
  the sharpest short-range bridges.
- The blind gap (2.92% fraud) sits slightly below average; with only 7,558
  rows this is within normal daily fluctuation.
- **Identity coverage drift** (26.7% → 17.7% → 21.0%, table above) is the
  one distribution shift found at this stage worth carrying forward.
- Nothing else deviated from expectations: shapes, uniqueness, day range,
  and base rate all matched the brief's stated values exactly.

## Episode-role convention (answering the gate question)

Episode roles are assigned on the **global chronological stream**, never
within a slice. An entity whose first strike lands on day 108 and which
reappears flagged on day 125 is **propagated** in validation, not a first
strike. This is now normative in `strikeone/episodes.py` and enforced by
`test_roles_are_global_across_slices`, whose fixture has exactly that
shape — first strike in train, later flagged transaction in validation —
and which also demonstrates that a per-slice computation would misclassify
it.

## Gate checklist

- [x] Holdout sealed with verifiable hash; rebuild reproduces it exactly
- [x] Access log exists, is committed, and is empty
- [x] Metrics module unit-tested (22/22) and committed
- [x] Slice row/positive counts reported (table above)
