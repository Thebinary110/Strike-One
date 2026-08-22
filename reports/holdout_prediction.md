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

## Falsifiable protocol claims

- Validation→holdout drop is *expected*: no drop at all would be more
  suspicious than a large one (it would suggest the holdout is not truly
  out-of-time for the pipeline).
- Sanity ceiling stands: pooled holdout ROC-AUC above ~0.95 is a bug
  report, not a result.
