# Stage 2 — Entity intelligence

## The surprise first

**Baseline B beat A by +0.17 AP (0.5734 → 0.7437, AUC 0.9184 → 0.9612) —
eight times the top of the expected band — and the investigation shows the
entire gain is the labeling rule echoing back through the features.** The
model learned to be a blocklist: at a fixed alert budget its recall on
*propagated* fraud jumped 40% → 75% while its recall on *first strikes* —
the transactions where loss is actually prevented — went 65.2% → 62.9%.
The transaction-level metric calls this a breakthrough; the episode lens
shows it is redundant catch. This is the submission's thesis, measured on
validation, under the correct protocol, before we even opened Stage 3.

Per the calibration rule ("any AP above ~0.65: stop and investigate"), the
result was not believed until the mechanism was isolated (below).

## A. UID reconstruction

`UID = card1 + "_" + addr1 + "_" + floor(day − D1)`, NaN components
stringified (faithful to the public kernels).

| Slice | Resolved (all 3 present) | D1 null | addr1 null | UID cardinality | txns/UID mean | p50 | p90 | p99 | max | singletons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 88.8% | 0.06% | 11.1% | 144,949 | 2.39 | 1 | 5 | 16 | 300 | 59.1% |
| val | 88.8% | 1.01% | 10.2% | 39,639 | 1.79 | 1 | 3 | 9 | 58 | 65.3% |
| holdout | 89.5% | 0.04% | 10.4% | 43,469 | 1.90 | 1 | 4 | 10 | 1,395 | 63.8% |

- Resolution is **88.8–89.5%, below the expected 95%+**. The driver is
  addr1 nulls (~11%), not D1 (0.2%). Fallback: NaN-stringified UIDs pool
  null-addr1 rows into coarser card1+first-seen-day pseudo-entities
  (documented in `entity.build_uid`); a `level` marker (3/2/1) tracks it.
- The distribution is extremely thin: median 1 transaction per UID, ~60%
  singletons. Entity history barely exists for most entities.
- One holdout UID has 1,395 transactions (noted; label-free observation).

## B. Entity novelty — history is structurally unavailable for half the traffic

Share of non-null rows whose key was never seen before (label-free;
holdout covariates read from the raw stream, never the sealed file — see
PROPOSALS P-007; no holdout label read anywhere):

| Key | val: novel vs train | holdout: vs train | holdout: vs all prior | null rate (val/holdout) |
|---|---:|---:|---:|---|
| **UID** | **52.4%** | **64.8%** | **51.7%** | 11.2% / 10.5% |
| card1 | 1.2% | 1.4% | 1.1% | 0% / 0% |
| addr1 | 0.03% | 0.00% | 0.00% | 10.2% / 10.4% |
| P_emaildomain | 0.00% | 0.00% | 0.00% | 15.8% / 18.1% |
| DeviceInfo | 2.8% | 3.8% | 1.8% | 86.2% / 83.1% |

- **Half of validation/holdout volume belongs to UIDs with zero history.**
  The novelty is created by the UID's first-seen-day component: the card
  and address vocabularies are stable, but new *clients* keep arriving.
  This explains the Stage 1 null structurally and caps what any
  entity-history feature can ever do here.
- 41.3% of val positives sit on novel UIDs; novel UIDs are slightly
  *less* fraudulent than seen ones (3.12% vs 3.86%).
- DeviceInfo is 83–86% null — its Stage 1 importance operates on a thin
  sliver, consistent with the identity-present stratification below.

## Carry-forward 3: the decay is staleness, not coverage

- Coverage over days 1–150 is a **step change at days 26–27** (−28.5pp in
  one day; weeks 1–3 run 40–52%, then a stable 14–25% regime). Train's
  26.7% average is an artifact of the early regime; within validation
  coverage is flat.
- Per-day AP: ρ(day) = −0.668 (p=0.0001); ρ(coverage) = +0.259 (p=0.18);
  ρ(day, coverage) = −0.06. Joint OLS: β_day = −0.646, β_coverage = +0.145.
  **Diagnosis: staleness. Fix: retraining cadence, not imputation.**
- Stratified (Baseline A, validation): identity-present n=14,161, fraud
  rate **9.80%**, AP 0.774 [0.753, 0.794], AUC 0.937; identity-absent
  n=65,793, rate 2.16%, AP 0.333 [0.308, 0.359], AUC 0.891. AP is
  base-rate-sensitive, so compare with the rates in view: relative to
  prior, lift is 7.9× (present) vs 15.4× (absent). Identity *presence*
  itself is a 4.5× base-rate signal — part of DeviceInfo's apparent
  importance is this population split.
- Figures: `stage2/fig_id_coverage_per_day.png`,
  `stage2/fig_ap_vs_day_and_coverage.png`.

## C. The UID aggregation family under a correct chronological split

55 point-in-time expanding aggregations (Amt mean/std, D1–D15 mean/std,
C1–C14 and M1–M9 means, all keyed by UID; UID itself excluded from the
matrix, as the original did). Reached-the-model checks: median val
non-null 49.8% (matching UID novelty), family gain share 11.5%, top
features `uidagg_TransactionAmt_mean` and D-column means.

| Metric | A | A + family | paired Δ | p(Δ≤0) |
|---|---|---|---|---|
| AP | 0.5734 [0.5544, 0.5907] | 0.5804 [0.5616, 0.5982] | **+0.0070 [+0.0019, +0.0122]** | 0.003 |
| ROC-AUC | 0.9184 | 0.9211 | **+0.0027 [+0.0002, +0.0050]** | 0.018 |

**Verdict: the famous lift survives a correct temporal split, at roughly a
quarter of its advertised size** (+0.0027 AUC vs the published +0.011
under month-wise GroupKFold). It is real, behavioural, delay-free — and
small, because half the evaluation rows have no history for it to
aggregate. This retires the Stage 1 overreach in both directions: the
family is neither leak-only (it survives) nor as valuable as its
reputation (GroupKFold's entity-overlap flattered it).

## D. Baseline B, with the groups separately ablatable

Behavioural: {card1, addr1, P_emaildomain, DeviceInfo, UID} × {1,7,30}d ×
{count, mean amount, velocity} = 45 features, no delay. Label-derived: per
key, prior labeled count and fraud rate under the **7-day delay** = 10
features. Feature computation runs over the full modeling stream with
prior-row-only machinery (a val row at day 130 may use labels of rows up
to day 123, exactly as a deployed system would); models fit on days 1–112.
Baseline A is already V-inclusive (V258/V294 in its top importances), so
the brief's yardstick requirement is satisfied by construction.

| Variant | AP | AUC | ΔAP vs A (paired) | p(Δ≤0) |
|---|---|---|---|---|
| A | 0.5734 [0.5544, 0.5907] | 0.9184 | — | — |
| A + behavioural | 0.5569 [0.5382, 0.5747] | 0.9119 | **−0.0165 [−0.0217, −0.0109]** | 1.000 |
| A + label-derived | 0.7461 [0.7320, 0.7603] | 0.9600 | +0.1727 [+0.1594, +0.1871] | 0.000 |
| B (both) | 0.7437 [0.7283, 0.7572] | 0.9612 | +0.1703 [+0.1570, +0.1845] | 0.000 |

- **Behavioural windows actively hurt** (−0.0165, decisively): ~50% novel
  UIDs make them NaN-heavy, and the val-period windows cross the
  delay-gap regime; the trees spend capacity on noise. (The UID family's
  +0.007 shows *expanding lifetime* aggregates help slightly where
  *short windows* do not.)
- **The label-derived gain is the labeling rule, not intelligence.**
  `lab_uid_fraud_rate` is B's top feature at gain 137,951 — 1.6× Baseline
  A's strongest feature. The host labels every transaction after an
  entity's first chargeback as fraud, so "entity has a known fraud ≥7 days
  old" nearly determines the label by construction.

### The investigation (`stage2/label_gain_investigation.json`)

At a fixed alert budget of 2,810 (= val positives; 1,610 first strikes +
1,200 propagated on the global-stream roles):

| Scorer | first-strike recall | propagated recall | precision |
|---|---:|---:|---:|
| A | **0.652** | 0.400 | 0.544 |
| B | 0.629 | **0.753** | 0.682 |
| pure blocklist (max delayed fraud-rate, no model) | 0.220 | 0.634 | 0.397 |

- B's headline gain is **entirely propagated re-capture**; first-strike
  recall does not improve (65.2% → 62.9%; Stage 3 will put a CI on the
  drop). A blocklist score alone — no model — reaches AP 0.435 / AUC 0.838.
- Honesty bounds: the 7-day label delay is optimistic (real chargebacks
  mature over ~30–120 days, and a "legit" label embeds up to 120 days of
  future silence), so +0.17 is an **upper bound** on label-feature value;
  the *qualitative* finding — the gain lives on propagated rows — is
  delay-invariant.

## Delay-gap check (Stage 0 carry-forward, decision recorded)

Mean label-derived fraud-rate features, val days 120–127 vs 128–147:
ratios 0.83–1.00 (uid 0.018 vs 0.022; all others ≈1). **No upward
displacement** — the feared 5.07%-week lookback effect does not materialise
because the features are expanding-lifetime, not last-week windows.
**Decision: keep the gap where it is and calibrate on all of validation;
no week dropped.** (`stage2/fig_delay_gap_check.png`.)

## Carry-forwards closed this stage

1. 2×2 claim narrowed in STAGE_1.md (and the Stage 2 experiment it
   deferred to is now done — see C).
2. Null verified: aggregates were used (top-20 gain) and redundant, not
   dropped; all four cells reproduced to 4 decimals.
3. Decay decomposed (above).
4. `reports/holdout_prediction.md` committed: pre-registered PRIMARY
   ranges (AP [0.32, 0.48], AUC [0.86, 0.91]) and SECONDARY refit-through-
   day-147 policy with nested calibration split, locked before unsealing.
5. CP@k steepness noted; demo k deliberately not chosen yet.

## Gate verdict on Stage 5, stated plainly

B's transaction-level gain survives its paired test — but it is the metric
distortion this submission exists to expose, not model value. Nothing in
Stage 2 produced a first-strike improvement: behavioural windows hurt, the
UID family adds +0.007 AP transaction-level (first-strike effect unknown,
Stage 3 will measure), and the label group only re-catches blocklisted
entities. **Recommendation: do NOT spend a day on Stage 5 graph features —
neighbour aggregates over a graph of past edges would chase the same
propagated signal — and reallocate that time to Stages 3/4, where the
episode analysis and decision policy now have exceptional material.** If
the human overrides, Stage 5's kill criterion should be first-strike lift,
not transaction-level lift.

## Holdout status

Access log verified empty (zero entries) by assertion at the end of every
Stage 2 script. No holdout label has been read by anything, ever.
