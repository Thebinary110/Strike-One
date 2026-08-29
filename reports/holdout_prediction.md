# Pre-registered holdout prediction and locked refit policy

Committed before the seal is broken. The holdout access log is empty at the
time of writing. Nothing in this file may be edited after Stage 7 opens the
holdout; if the actual lands outside the ranges below, that is a finding to
be reported, not a reason to iterate.

## Locked evaluation policy for Stage 7 (binding)

Two holdout numbers will be reported, and only these:

1. **PRIMARY — the frozen day-112 pipeline.** Model(s) exactly as frozen at
   the Stage 1/2 gates (config hash `904a84eb…` for A; B likewise frozen at
   its gate), trained on days 1–112 only. Fully clean, zero methodological
   ambiguity, deliberately handicapped by ~39–70 days of staleness.
2. **SECONDARY — the same frozen recipe refit on days 1–147.** Identical
   features, hyperparameters, and tree count selected by the frozen
   protocol; base model refit on days 1–147. Calibration is fitted on a
   nested inner chronological split (fit days 1–133, calibrate on days
   134–147), then the base model is refit on days 1–147 keeping that
   calibration map. **Calibration is never fitted on the holdout.**

The PRIMARY−SECONDARY delta quantifies the value of retraining cadence,
turning the staleness handicap into a measured product argument.

## Predicted ranges (PRIMARY, pooled over days 151–182)

Basis, all from validation-period evidence, committed before unsealing:

- Weekly per-day AP means across validation decay 0.698 → 0.561 → 0.517 →
  0.469 (weeks 1–4 past the day-119 boundary edge): a steep first-week
  cliff, then ≈ −0.045/week and decelerating.
- The Stage 2 decay decomposition attributes this to staleness, not
  identity coverage (β_day = −0.65 vs β_coverage = +0.15; coverage is flat
  within validation while AP falls).
- Holdout occupies weeks ~5–9 past the training boundary (midpoint ~55
  days vs ~21 for validation). Naive linear extrapolation of the late-val
  slope lands near 0.35 by the holdout midpoint; the observed deceleration
  argues the truth is somewhat higher. Two small compositional tailwinds:
  holdout identity coverage is 21.0% vs validation's 17.7% (the
  identity-present stratum ranks far better), and holdout fraud rate
  (3.48%) matches validation (3.51%), so no base-rate correction applies.
- ROC-AUC decays much more slowly than AP on this data (AUC compresses
  near 1; the competition winner lost 2.2 AUC points public→private under
  a comparable staleness gap).

**Predicted, PRIMARY (frozen day-112), pooled holdout:**

| Quantity | Central | Range |
|---|---|---|
| Average precision | ~0.40 | **[0.32, 0.48]** |
| ROC-AUC | ~0.885 | **[0.86, 0.91]** |

**Predicted, SECONDARY (refit through day 147):** staleness at the holdout
midpoint (~19 days) then matches validation's (~21 days), so the secondary
should land near validation levels: AP **[0.50, 0.62]**, ROC-AUC
**[0.90, 0.93]**. Implied retraining value: roughly +0.1 to +0.2 AP.

These ranges are stated for the shipped model's headline scores. Stage 2
measured B ≈ A + at most a small delta (UID family +0.005 AP), so the
ranges hold whichever of A/B ships; they are priors to be surprised by,
not targets to hit. A result far outside them means first "look for a
bug", and only then "update the theory".

## Extension, committed before the seal opens (Stage 7 gate requirement)

### A. The risk to the punchline, predicted in advance

Holdout entity novelty is higher than validation's (67.4% of rows on
never-seen-in-train UIDs vs 55.8%; 54.9% vs all-prior data vs 52.7%).
Two consequences, called now:

1. **The routing gap should NARROW.** Fewer already-flagged entities mean
   lane 1 covers proportionally less traffic, so the redundancy that
   routing removes from the ranking population is smaller. Predictions:
   holdout lane-1 row share **below validation's 2.14%** (roughly
   1.2–2.0%), lane-1 share of positives **below validation's 33.0%**
   (roughly 18–30%), and the routing-inoculation ratio for B at ~18
   alerts/day **narrowing from validation's 3.1× to roughly 1.5–2.8×** —
   still material, but visibly smaller.
2. **The distortion itself should be WEAKER on holdout.** A smaller
   propagated share of positives (validation: 63.0%; predicted holdout:
   roughly 45–60%) leaves less for the headline scorer to feed on.
   Predictions: **B's AP advantage over A shrinks from validation's +0.17
   to roughly +0.06 to +0.14**; the three-system precision/prevention
   inversion **persists directionally** (blocklist and B posting higher
   transaction precision than A at matched budgets while catching fewer
   or zero first strikes) with smaller magnitude; B's first-strike
   deficit at tight budgets persists but compressed.

If the distortion shrinks as called, that is evidence *about the
mechanism* (the distortion scales with the propagated share, exactly as
the label-propagation account requires). Stated before any holdout number
was seen.

### B. Pre-registered analysis plan — nothing added or dropped after the
numbers are seen

Exactly these figures, in exactly this order, at exactly these operating
points. Primary comparisons are marked; everything else is secondary.

1. **[PRIMARY] Headline range check** — Baseline A (frozen booster
   `baseline_a.txt`, config 904a84eb) on all holdout rows: AP and ROC-AUC
   against the ranges above (AP [0.32, 0.48], AUC [0.86, 0.91]).
2. **[PRIMARY] Distortion size** — B (Stage 2 recipe refit on days 1–112
   with early stopping on validation, saved before unsealing) on all
   holdout rows: AP/AUC; B−A AP gap against prediction A.2.
3. **[PRIMARY] The inversion** — at the blocklist's natural holdout
   operating point N: blocklist / A / B transaction precision and
   first-strike catches at budget N (the three-system table).
4. **[PRIMARY] Routing inoculation** — B routed vs unrouted first-strike
   recall at 18 alerts/day (576 alerts) against prediction A.1.
5. Episode table at the stated default (100 alerts/day → 3,200 alerts
   over 32 days): shipped two-lane+A2, single-lane B, single-lane A,
   blocklist — FS recall, friction efficiency, redundancy rate,
   transaction precision. **The two console counters at this point.**
6. First-strike recall and friction efficiency across the capacity curve
   (per-day grid {5,10,18,25,36,50,71,100,140,200,280,400,500}), all four
   scorer×routing configurations.
7. **SECONDARY refit** — headline AP/AUC of the day-147 refit (policy in
   C) against ranges (AP [0.50, 0.62], AUC [0.90, 0.93]); the
   primary-vs-secondary delta as the price of retraining cadence; plus
   the secondary two-lane counters at 100/day.
8. Loss-weighted first-strike recall at the default budget, primary
   system (validation reference: 0.415).

Bootstrap CIs (1,000 resamples, seed as everywhere) on items 1, 2, and
the B−A first-strike delta in item 5; uid-cluster bootstrap for episode
metrics. Roles computed on the global 1–182 stream under the fixed pooled
convention. No other figures will be computed on the holdout, and none of
the above will be dropped, whatever they show.

### C. Locked reporting policy, restated

PRIMARY = the frozen day-112 pipeline exactly as committed (A:
`904a84eb…`; A2 + routing + isotonic map: `b632a136…`). SECONDARY = the
same recipes refit through day 147: tree count chosen by the nested inner
split (fit days 1–133, early-stop/calibrate on days 134–147), base model
then refit on days 1–147 at that tree count, keeping the nested
calibration map. **Calibration is never fitted on the holdout.** Both are
reported; the delta prices retraining cadence. The holdout is opened
exactly once, by one script, logging exactly one access.

## Falsifiable protocol claims

- Validation→holdout drop is *expected*: no drop at all would be more
  suspicious than a large one (it would suggest the holdout is not truly
  out-of-time for the pipeline).
- Sanity ceiling stands: pooled holdout ROC-AUC above ~0.95 is a bug
  report, not a result.
