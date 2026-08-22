# Stage 1 — Baseline A and the leakage demonstration

## Baseline A

LightGBM on transaction + identity features only — no entity aggregates.
Fit on train (days 1–112), evaluated on validation (days 120–147). Holdout
untouched (access log verified empty at the end of every script run).

**Hyperparameters are deliberately modest and unsearched** (rationale in
`scripts/stage1_baseline_a.py`): lr 0.05, 64 leaves, min_child_samples 100,
feature/bagging fraction 0.8, up to 4000 trees with early stopping (200
rounds) on validation AP — validation is the designated tuning slice, so
early stopping on it is its job, documented here rather than hidden.
Stopped at **391 trees**.

### Headline numbers (validation, 1000-resample bootstrap CIs)

| Metric | Value | 95% CI |
|---|---|---|
| Average precision | **0.5734** | [0.5544, 0.5907] |
| ROC-AUC | **0.9184** | [0.9122, 0.9243] |

Calibration against expectations: ROC-AUC sits at the top edge of the
anticipated 0.88–0.92 band — no alarm, but noted. The AP figure is the
number we are establishing; there is no trustworthy published temporal-split
PR baseline for this dataset to compare against.

### Card Precision@k (per-day card ranking, card1 as the card key)

| k | 10 | 25 | 50 | 100 |
|---|---|---|---|---|
| precision | 0.921 | 0.851 | 0.665 | 0.432 |

At ~100 positives across ~2,900 transactions per validation day, k=100 is
near the degenerate point where precision@k ≈ recall@k; the curve is
reported so the demo k can be chosen deliberately later.

### Per-day AP: performance decays with distance from the training boundary

Spearman ρ(day, AP) = **−0.668 (p < 0.001)**; mean AP over days 120–133 is
**0.629**, over days 134–147 it is **0.493**. Days 120–126 run 0.59–0.75;
days 139–147 run 0.28–0.57 (worst: day 139 at 0.28). Individual days are
noisy (60–180 positives each) but the trend is unambiguous.

**Production reading:** a model this shape loses roughly a quarter of its
ranking quality (by AP) within four weeks of staleness. That is direct
evidence for a 1–2 week retraining cadence, and it is measured under the
honest protocol — a random-CV evaluation is structurally incapable of
seeing it. (CSV: `stage1/baseline_a_perday_ap.csv`, figure:
`stage1/fig_perday_ap.png`.)

### Feature hygiene

Full list (437 features, 31 categorical) and every exclusion with its
reason: `reports/stage1/baseline_a_frozen.json`. Exclusions: `isFraud`
(label), `TransactionID` (verified monotonic in TransactionDT — pure time
proxy), raw `TransactionDT`, `day`, `day_idx` (monotonic time proxies).
Derived: hour-of-day and day-of-week, raw + sin/cos (the dow phase is
arbitrary since the DT reference is unknown; only periodicity matters).
Categorical vocabularies are fitted on train only; unseen validation values
map to missing. High-cardinality numeric IDs stay numeric (PROPOSALS
P-004).

### Top-20 importances (gain), with suspicion notes

V258, C1, DeviceInfo, C14, card2, C13, V294, card1, TransactionAmt, addr1,
R_emaildomain, D2, P_emaildomain, id_31, D15, C11, card5, D10, dist1, id_30.

- **V258/V294 near the top is context for Stage 2, not a leak**: V-columns
  are Vesta's own pre-computed "ranking/counting/entity relation" features.
  Baseline A is therefore already V-inclusive — exactly the baseline the
  brief demands entity-aggregate lift be measured against.
- **DeviceInfo at #3 deserves suspicion**: identity coverage drifts 26.7%
  (train) → 17.7% (val) → 21.0% (holdout), so part of its gain may encode
  "has an identity record at all", a population signal that shifts across
  periods. Watch it in Stage 2.
- D2/D15/D10 are raw "days since X" timedeltas — not monotonic time
  proxies per row, but cohort-drifting; normalization is logged as
  PROPOSALS P-006.
- No excluded time proxy re-entered through a derived feature.

### Freeze

Config (params + feature list + exclusions + model file SHA-256) frozen in
`reports/stage1/baseline_a_frozen.json`; config hash
`904a84eb1a9b715fda12ea9c038c4f5e69c3142c4999c0449f1875d1828f5491`.
The model file itself is gitignored (large) but rebuilds deterministically
from the frozen config and seed.

## The 2×2 leakage table

Standalone diagnostic (`scripts/stage1_leak_table.py`), not the shipped
model. Same row pool everywhere (train ∪ val slices); the random split
matches the chronological eval size (79,954 rows); every cell trains at
Baseline A's frozen capacity (391 trees, no early stopping) so no cell gets
eval-set model selection. Aggregates added on top of Baseline A's features
are deliberately minimal and **label-free**: transaction count and mean
amount per card1, computed whole-dataset vs expanding point-in-time.

### Average precision (95% bootstrap CIs)

| split \ aggregates | whole-dataset | expanding (point-in-time) |
|---|---|---|
| **random** | 0.7976 [0.7837, 0.8108] ⚠ BOTH LEAKS | 0.7862 [0.7720, 0.7993] (split leak only) |
| **chronological** | 0.5725 [0.5530, 0.5903] (agg leak only) | **0.5734 [0.5540, 0.5910] ← HONEST** |

### ROC-AUC

| split \ aggregates | whole-dataset | expanding (point-in-time) |
|---|---|---|
| **random** | 0.9592 [0.9547, 0.9636] ⚠ BOTH LEAKS | 0.9560 [0.9513, 0.9605] (split leak only) |
| **chronological** | 0.9208 [0.9153, 0.9261] (agg leak only) | **0.9196 [0.9138, 0.9250] ← HONEST** |

### Decomposition — the split leak dominates, and it isn't close

| Component | AP | ROC-AUC |
|---|---:|---:|
| Split leak (random+pit − chrono+pit) | **+0.2128** | **+0.0364** |
| Aggregation leak (chrono+whole − chrono+pit) | −0.0009 | +0.0012 |
| Interaction | +0.0123 | +0.0019 |
| **Total inflation (random+whole − honest)** | **+0.2242** | **+0.0396** |

Paired bootstrap on shared eval rows (whole vs point-in-time):

| Comparison | Δ AP | 95% CI | p(Δ≤0) |
|---|---:|---|---:|
| under random split | +0.0114 | [+0.0084, +0.0147] | 0.000 |
| under chronological split | −0.0009 | [−0.0052, +0.0034] | 0.651 |

### Reading, carefully — the claim, no wider than the evidence

1. **A random split inflates AP by +0.22 — 39% relative — on the identical
   feature set.** Anyone reporting random-CV numbers on this dataset is
   reporting the top-left row. The ROC-AUC inflation (+0.04) looks small
   only because AUC compresses near 1; in AP terms the honest number is
   0.57, not 0.80.
2. **What the two card1 aggregates support:** behavioural entity
   aggregates of this minimal kind carry no independent signal under a
   correct chronological split (−0.0009, CI spans zero); their apparent
   value under a random split (+0.0114, decisively non-zero) is
   entity-overlap memorisation — and label propagation makes that
   memorisation near-total, because once a card is positive it stays
   positive, so any of its training rows reveal the labels of the rest.
3. **What they do NOT support:** any claim about the competition's UID
   aggregation family (~45 features, validated under month-wise
   GroupKFold, worth +0.011 AUC there). Whether *that* lift survives a
   correct chronological split is a Stage 2 experiment, not a Stage 1
   conclusion.
4. **Scope honestly stated:** this decomposition is for *behavioural*
   (label-free) aggregates. Label-derived aggregates (target encodings)
   are a different, larger hazard — they carry the delay/leak asymmetry
   invariant 3 exists for — and were deliberately not tested here because
   the minimal-aggregate design isolates the split effect cleanly.
5. Incidental: point-in-time card1 count/mean added ~nothing over Baseline
   A under the honest protocol (0.5734 → 0.5734, but see the null
   verification below). Consistent with the brief's Stage 2 calibration;
   foreshadows that Stage 2's gate is a real hurdle, not a formality.

### Null verification (the 0.5734 → 0.5734 coincidence)

Identical-to-four-decimals is also the signature of features that never
reached the model, so the run was repeated with reached-the-model
diagnostics per cell (now permanent in the script; all four cell metrics
reproduced exactly, confirming determinism). In the honest cell:

| Feature | non-null (train/eval) | unique | gain share | gain rank /439 |
|---|---|---:|---:|---:|
| pit_card1_count | 100% / 100% | 9,670 | 1.5% | 17 |
| pit_card1_amt_mean | 96.9% / 99.2% | 349,265 | 2.1% | 10 |

The aggregates were present, non-constant, near-fully populated, and the
model gave them top-20 gain out of 439 features — and AP still did not
move. The null is "**used but redundant**" (the model reallocated splits it
would otherwise have spent on C/V-columns), not "silently dropped". In the
random cells the same features rank 5–14, consistent with the
memorisation reading.

Raw numbers: `stage1/leak_table.json`; screenshot table:
`stage1/leak_table.md`.

## Holdout status

`reports/holdout_access.log` verified empty (zero entries) by assertion at
the end of both Stage 1 scripts. The holdout has never been read.
