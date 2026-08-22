# PROPOSALS

Running log of judgment calls outside the brief, per §5. Each entry: case,
estimated cost, recommendation, status.

## P-001 — Data source: HuggingFace mirror instead of Kaggle API
The Kaggle competition download requires an authenticated account that has
accepted the competition rules; that breaks "reproducible from a clean clone
with one command". An ungated public mirror
(`aliceczr/ieee-fraud-detection` on HuggingFace) serves the identical files;
we pin SHA-256 checksums of both raw files in `data/raw_checksums.sha256`
and verify shapes (590,540×394 / 144,233×41) at load time, so a corrupted or
divergent mirror fails loudly. **Cost:** 0h (done). **Recommendation:**
adopt; revisit only if the mirror disappears (fallback: document the Kaggle
CLI path in the README). **Status: implemented (Stage 0).**

## P-002 — Split boundaries kept as proposed, with evidence
Checked daily/weekly volume and fraud rate across days 1–150 before
accepting the brief's round-number boundaries. Findings: (a) the only regime
shift in the data — ~30–70% higher volume with a *lower* fraud rate over
days 1–28 — falls entirely inside train; (b) no structural break near days
112/120 or 147/151; (c) the delay gap (113–119) happens to be the
highest-fraud-rate week in the modeling range (5.07% vs 3.4–3.5% for its
neighbours), but it is discarded, not fitted or evaluated on, so it biases
nothing — worth a sentence in the final report. Val (28d) and holdout (32d)
each span 4 full weekly cycles. **Cost:** 0.5h (done). **Status: adopted.**

## P-004 — High-cardinality numeric IDs treated as numeric, not categorical
`card1` (~13k values), `card2/3/5`, `addr1/2` arrive as numerics. LightGBM's
native categorical handling on 10k+ categories overfits small leaves; the
numeric treatment is the common published baseline and keeps Baseline A
modest. String columns (31 of them) use native categoricals with
train-fitted vocabularies; unseen values map to missing, never to a fresh
code. **Cost:** 0h. **Alternative logged:** CatBoost ordered target
encoding — only worth a paired comparison if Stage 2 lift is marginal.
**Status: adopted for Stage 1.**

## P-005 — Leak table: fixed capacity, sanctioned random split
The 2x2 uses a random split, which invariant 1 bans for modeling; here it
is the *object of study*, labeled as such, in a standalone script nothing
downstream consumes. All four cells train at Baseline A's early-stopped
capacity (391 trees) with no early stopping, so no cell benefits from
eval-set model selection and the deltas isolate the leaks, not tuning.
**Status: adopted (Stage 1).**

## P-006 — D-column normalization deferred to Stage 2
D-columns are "days since X" timedeltas; public solutions often use
`D - day` to make them cohort-stable. Baseline A keeps them raw (modest
baseline, standard practice). If Stage 2's entity features underperform,
this is the first cheap variant to test — est. 1h. **Status: logged.**

## P-003 — Integer-day convention for split membership
`day = TransactionDT/86400` is float (1.000–182.999). Slice membership uses
`day_idx = floor(day)`, inclusive bounds, so every row belongs to exactly
one slice and the total row count is asserted to equal 590,540 at build
time. Feature code uses the float `day` where sub-day resolution matters.
**Status: adopted.**
