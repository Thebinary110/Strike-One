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

   | Slice | Days | Rows | Positives | Fraud rate | Amount sum |
   |---|---|---:|---:|---:|---:|
   | Train | 1–112 | 389,523 | 13,350 | 3.43% | 52,432,828 |
   | Delay gap | 113–119 | 21,078 | 1,069 | 5.07% | 2,807,307 |
   | Validation | 120–147 | 79,954 | 2,810 | 3.51% | 10,788,560 |
   | Blind gap | 148–150 | 7,558 | 221 | 2.92% | 983,656 |
   | **Holdout** | **151–182** | **92,427** | **3,213** | **3.48%** | 12,726,594 |

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
  evaluated on — so it biases nothing, but it means the 7 days we throw
  away are unusually fraud-dense. Noted for honesty, not action.
- The blind gap (2.92%) and week 21 generally sit slightly below average
  fraud rate; with only 7,558 rows this is within normal daily fluctuation.
- Nothing else deviated from expectations: shapes, uniqueness, day range,
  and base rate all matched the brief's stated values exactly.

## Gate checklist

- [x] Holdout sealed with verifiable hash; rebuild reproduces it exactly
- [x] Access log exists, is committed, and is empty
- [x] Metrics module unit-tested (22/22) and committed
- [x] Slice row/positive counts reported (table above)
