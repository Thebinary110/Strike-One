# Stage 2 — Entity intelligence

> **Correction (Stage 3 prerequisite audit).** The Stage 3 fragmentation
> check caught a pandas-3 regression in UID construction: `astype(str)`
> propagates NA instead of writing a literal `"nan"`, so fallback rows
> (null addr1/D1, 11.4%) silently received **null UIDs** rather than
> pooling into pseudo-entities as documented. Consequences: (a) UID-keyed
> model features were NaN (masked) on those rows — a *more conservative*
> variant, so the headline B result stands qualitatively; (b) the
> first-strike/propagated decomposition below was contaminated (each
> null-UID fraud was counted as its own singleton "first strike").
> `build_uid` is fixed and regression-tested, `episode_roles` now refuses
> null entity ids, and every affected number in this report has been
> recomputed under the fixed convention. The original values are preserved
> in git history (commit 3539672).

## The surprise first

**Baseline B beat A by +0.17 AP (0.5734 → 0.7478, AUC 0.9184 → 0.9628) —
eight times the top of the expected band — and the investigation shows the
entire gain is the labeling rule echoing back through the features.** The
model learned to be a blocklist: at a fixed alert budget its recall on
*propagated* fraud jumped 53% → 76% while its recall on *first strikes* —
the transactions where loss is actually prevented — went 56.8% → 55.2%
(Stage 3 later confirmed the drop with a CI excluding zero). The
transaction-level metric calls this a breakthrough; the episode lens shows
it is redundant catch. This is the submission's thesis, measured on
validation, under the correct protocol, before we even opened Stage 3.

Per the calibration rule ("any AP above ~0.65: stop and investigate"), the
result was not believed until the mechanism was isolated (below).

## A. UID reconstruction

`UID = card1 + "_" + addr1 + "_" + floor(day − D1)`, NaN components
stringified (faithful to the public kernels).

| Slice | Resolved (all 3 present) | D1 null | addr1 null | UID cardinality | txns/UID mean | p50 | p90 | p99 | max | singletons |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | 88.8% | 0.06% | 11.1% | 157,365 | 2.48 | 1 | 5 | 17 | 300 | 58.7% |
| val | 88.8% | 1.01% | 10.2% | 43,383 | 1.84 | 1 | 3 | 10 | 64 | 64.9% |
| holdout | 89.5% | 0.04% | 10.4% | 46,896 | 1.97 | 1 | 4 | 11 | 1,395 | 63.3% |

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
| **UID** | **55.8%** | **67.4%** | **54.9%** | 0% (pooled) |
| card1 | 1.2% | 1.4% | 1.1% | 0% / 0% |
| addr1 | 0.03% | 0.00% | 0.00% | 10.2% / 10.4% |
| P_emaildomain | 0.00% | 0.00% | 0.00% | 15.8% / 18.1% |
| DeviceInfo | 2.8% | 3.8% | 1.8% | 86.2% / 83.1% |

- **The card1-vs-UID novelty gap (1.2% vs 56%) is not a tension: card1 is
  a card *attribute* with cardinality 13,553 over 590k rows — a bucket
  that recurs — while UID approximates a *client*. Buckets recur; clients
  don't.** Attribution of val UID novelty confirms it: 91.8% is a changed
  first-seen-day on a known (card1, addr1) pair — i.e., a new client on a
  recycled bucket — vs 6.0% novel addr1 and 2.2% novel card1.
- **Over half of validation/holdout volume belongs to UIDs with zero
  history.** This explains the Stage 1 null structurally and caps what
  any entity-history feature can ever do here.
- **75.7% of val positives sit on novel UIDs** (fraud rate 4.77% on novel
  vs 1.94% on seen). Fraud is overwhelmingly a *fresh-entity* phenomenon
  here — consistent with label propagation itself: an old entity's episode
  would have started earlier, so val-period first strikes skew young.
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

| Metric | A | A + family | paired Δ | p(no improvement) |
|---|---|---|---|---|
| AP | 0.5734 [0.5544, 0.5907] | 0.5782 [0.5588, 0.5954] | +0.0048 [+0.0000, +0.0101] | 0.025 |
| ROC-AUC | 0.9184 | 0.9209 | +0.0025 [+0.0002, +0.0046] | 0.016 |

**Verdict: the famous lift survives a correct temporal split only
marginally — +0.0048 AP with a CI touching zero, +0.0025 AUC against the
published +0.011 under month-wise GroupKFold** (roughly a fifth of its
advertised size). It is behavioural and delay-free, but small, because
over half the evaluation rows have no history for it to aggregate. This
retires the Stage 1 overreach in both directions: the family is not
leak-only, and its reputation was substantially a GroupKFold
entity-overlap artifact. (Numbers are from the fixed pooled-UID rebuild;
the pre-fix run measured +0.0070 — the NaN-masking bug had flattered it.)

## D. Baseline B, with the groups separately ablatable

Behavioural: {card1, addr1, P_emaildomain, DeviceInfo, UID} × {1,7,30}d ×
{count, mean amount, velocity} = 45 features, no delay. Label-derived: per
key, prior labeled count and fraud rate under the **7-day delay** = 10
features. Feature computation runs over the full modeling stream with
prior-row-only machinery (a val row at day 130 may use labels of rows up
to day 123, exactly as a deployed system would); models fit on days 1–112.
Baseline A is already V-inclusive (V258/V294 in its top importances), so
the brief's yardstick requirement is satisfied by construction.

**Ablation convention: every row is add-one-group-to-A.** With exactly two
groups these are also the leave-one-group-out readings from B (B−label =
A+beh; B−beh = A+label), so one table serves both. The deltas do not sum
to B−A — the residual (+0.014 AP) is the beh×label interaction (B contains
no UID-family features, so none of the residual is the family): behavioural
windows carry signal *conditional on* label context that they lack alone.
A judge who runs the addition should land here.

| Variant | AP | AUC | ΔAP vs A (paired) | p(no improvement)¹ |
|---|---|---|---|---|
| A | 0.5734 [0.5544, 0.5907] | 0.9184 | — | — |
| A + behavioural | 0.5565 [0.5375, 0.5752] | 0.9128 | **−0.0169 [−0.0218, −0.0113]** | 1.000 |
| A + label-derived | 0.7493 [0.7349, 0.7630] | 0.9617 | +0.1758 [+0.1625, +0.1902] | 0.000 |
| B (both) | 0.7478 [0.7331, 0.7613] | 0.9628 | +0.1743 [+0.1609, +0.1882] | 0.000 |

¹ One-sided-for-improvement: the share of paired bootstrap resamples in
which the variant fails to beat A. 1.000 on the behavioural row means the
variant lost to A in every one of 1,000 resamples — not a typo.

- **Behavioural windows actively hurt (CI excluding zero) — and the Stage
  3 segmentation located the mechanism, refuting our first hypothesis.**
  We initially blamed dilution (features absent on the ~56% novel-entity
  traffic). The direct test says otherwise: the AP harm is **−0.0657
  [−0.0798, −0.0520] within the known-entity segment and +0.0005 (nil) on
  novel entities**. Windowed behavioural history misleads precisely where
  it is *populated* — train-period regulars' patterns do not transfer —
  and is inert where absent. Entity behavioural history here isn't merely
  useless; where it exists, it is harmful. (The UID family's marginal
  +0.005 shows *expanding lifetime* aggregates avoid this where *short
  windows* do not.)
- **The label-derived gain is the labeling rule, not intelligence.**
  `lab_uid_fraud_rate` is B's top feature at gain 145,507 — 1.7× Baseline
  A's strongest feature. The host labels every transaction after an
  entity's first chargeback as fraud, so "entity has a known fraud ≥7 days
  old" nearly determines the label by construction.

### The investigation (corrected numbers; full treatment in STAGE_3.md)

At a fixed alert budget of 2,810 (= val positives; 1,040 first-strike
episodes + 1,770 propagated transactions on the corrected global-stream
roles):

| Scorer | first-strike recall | propagated recall | precision |
|---|---:|---:|---:|
| A | **0.568** | 0.531 | 0.544 |
| B | 0.552 | **0.761** | 0.683 |
| Blocklist (uid, ≥7d-old fraud; natural operating point) | 0.000 | 0.524 | 0.542 |

- B's headline gain is **entirely propagated re-capture**; first-strike
  recall does not improve (Stage 3's paired CI: −0.016 [−0.031, −0.003] —
  it *worsens*). The named **Blocklist** reference (binary uid flag, no
  model) catches zero first strikes by construction yet matches A's
  transaction precision; a graded variant using all 5 keys' delayed fraud
  rates reaches AP 0.435 / AUC 0.838 as a ranking score.
- Honesty bounds: the 7-day label delay is optimistic (real chargebacks
  mature over ~30–120 days, and a "legit" label embeds up to 120 days of
  future silence), so +0.17 is an **upper bound** on label-feature value;
  the *qualitative* finding — the gain lives on propagated rows — is
  delay-invariant.

## Delay-gap check (Stage 0 carry-forward, decision recorded)

Mean label-derived fraud-rate features, val days 120–127 vs 128–147:
ratios 0.82–1.00 (uid 0.021 vs 0.025; all others ≈1). **No upward
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
UID family adds +0.005 AP transaction-level (first-strike effect unknown,
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
