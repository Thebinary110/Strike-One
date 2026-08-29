# Second holdout access — results against the pre-registration

Pre-registered in `reports/holdout_prediction.md` at commit **67d35f7**,
before unsealing. One unsealing, executed by `scripts/stage8_access2.py`;
the access log now holds exactly two entries, the second citing that
commit. The shipped system was frozen before this access and nothing
here changes it.

## 1. Rank-by-amount and random baselines (matched budgets)

At the primary operating point, 3,200 alerts (100/day × 32 days):

| system | first-hit recall | loss-weighted first-hit recall | precision | blocklist-coverable share | FPs |
|---|---|---|---|---|---|
| random | 3.8% | 0.0342 | 3.4% | 57% | 3,092 |
| rank-by-amount | 5.3% | **0.3447** | 5.5% | 64% | 3,023 |
| single-lane A | 55.6% | 0.4382 | 50.6% | 59% | 1,581 |
| single-lane B | 53.7% | 0.3958 | 64.6% | 69% | 1,132 |
| single-lane A2 | 57.5% | 0.4636 | 47.6% | 55% | 1,677 |
| shipped two-lane+A2 | 58.3% | **0.4733** | 45.7% | 69% | 2,701 |

(The shipped row's alert count is 4,975: lane-1's 1,775 standing blocks
ride on top of the 3,200 reviewed alerts and are included in its
precision/FP figures. Full k-curve at 7 budgets:
`baselines_kcurve.csv`.)

**The headline metric is unweighted first-hit recall**: shipped 58.3%
of cases vs rank-by-amount's 5.3% at the same budget (11×), at 45.7% vs
5.5% precision. On the metric that has to be *usable* — cases caught,
alerts an analyst can act on — the no-model baseline is nowhere.

**Loss-weighted first-hit recall is secondary, and is only ever reported
with the rank-by-amount row beside it.** The reason is structural: any
loss-weighted metric partially rewards amount-ranking by construction —
its numerator is denominated in the ranking key — so a sort-by-amount is
the mandatory yardstick for it, and here that yardstick scores 0.3447
against the shipped 0.4733 (73%). Our pre-registered prediction (the
registered primary comparison was loss-weighted) called 0.05–0.20 and a
≥2× margin: **missed on magnitude, held on direction** — the shipped
system stays ahead at every budget in the grid (1.26×–1.83×), but the
honest sentence is that if loss-weighted coverage were your only
objective and ~95% false positives were tolerable, sorting by amount
gets most of the way. This is less a fact about the shipped system than
about loss-weighted metrics: they are weak discriminators because they
partly measure "did you sort by amount".
The random floor landed as predicted (~budget share on everything).

## 2. Label-maturity sweep (evaluation-side only)

Shipped − single-lane-B first-hit recall at 3,200 alerts, uid-cluster
bootstrap CIs; lane-1 rebuilt per delay:

| delay | lane-1 flags | coverage of labelled fraud | lane-1 precision | delta (shipped − B) | 95% CI |
|---|---|---|---|---|---|
| 1d | 2,362 | 38.8% | 52.8% | +0.0543 | [+0.041, +0.068] |
| 3d | 2,086 | 32.9% | 50.6% | +0.0476 | [+0.034, +0.061] |
| 7d | 1,775 | 27.5% | 49.8% | +0.0459 | [+0.033, +0.058] |
| 14d | 1,542 | 23.2% | 48.3% | +0.0442 | [+0.032, +0.057] |
| 30d | 1,252 | 18.2% | 46.7% | +0.0434 | [+0.031, +0.057] |

**No reversal anywhere in 1–30 days; the conclusion survives at 30
days.** The delta decays far more slowly than the blocklist itself
(coverage halves, the delta loses only a fifth), because the shipped
system's first-hit advantage comes mostly from the lane-2 scorer's
ranking, not from lane-1 volume. Predictions: "stays positive, no
reversal" — **held**; magnitude at 30d predicted +0.01..+0.04, actual
+0.0434 — just above the band's top (a small favourable-side miss);
lane-1 size at 30d predicted 1,300–1,700, actual 1,252 — just below the
band (the blocklist shrinks slightly faster than we guessed).

**Scope limit, restated:** the sweep varies maturity on the evaluation
side only (episode/blocklist construction). B's label-derived features
remain trained at 7 days; a fully consistent sweep would retrain B per
delay, and we did not.

## 3. The cost claim, rebuilt (replacing the withdrawn "81/81")

The original Stage-4 claim compared the cost policy to fixed thresholds
on the same validation slice used to judge both — fixed thresholds are a
nested special case of cost policies, so unanimity there was close to
tautological, and tuning + judging on the same data is the classic
selection-on-evaluation error (Cawley & Talbot, JMLR 2010). That
phrasing is withdrawn; `reports/STAGE_4.md` carries the banner.

Rebuild: the frozen policy (isotonic calibration fitted on validation
only — the frozen Stage-4 map, asserted) against a single fixed
threshold on the *same* calibrated probabilities, tuned **per corner on
validation** (101 quantile thresholds minimising validation realized
cost), then **both evaluated on holdout rows**, per corner of the
original 81-corner (s=0) declared-range grid, with 400-resample
row-bootstrap CIs on (cost_fixed − cost_policy)/cost_approve-all.

**Result: 81 of 81 corners with 95% CIs excluding zero in the policy's
favour; median edge +14.4% of approve-all cost, IQR [+9.3%, +20.5%],
weakest corner +3.4%.** Prediction: k in [35, 65], median +1% to +4% —
**missed on the favourable side, twice**. We predicted unanimity would
die out-of-sample; it did not, and the median edge is ~4× our upper
guess.

**Decomposed, so the number is attributed to the right cause.** The
81/81 compares a three-action policy to a two-action threshold, so it
bundles two different advantages. Split apart:

| contrast | result | what it measures |
|---|---|---|
| three-action cost policy vs best two-action fixed threshold (holdout, this access) | **81/81, median +14.4%** | mostly the value of HAVING a step-up action at all |
| amount-aware vs amount-blind three-action (validation, Stage 4) | **55/81, central gap 0.04%** | the value of cost-derived thresholding itself |

**Most of the advantage is the action set, not the arithmetic.** A
two-action threshold must buy fraud protection with hard blocks of good
customers; step-up prices the middle, and that is where the +14.4%
lives. The cost-derived, amount-aware argmin itself is worth
approximately nothing over an amount-blind three-way split (Stage 4's
own negative finding, kept). The counterfactual assumption feeds the
first row directly: **a blocked fraudulent transaction is assumed fully
avoided, and a stepped-up one avoided with probability e** — not
measurable in this data. No single-point cost figure is stated, here or
anywhere.

### Where the advantage breaks: the extended e sweep

The original declared range floored e at 0.6, which means the grid never
tested the assumption the whole result rests on. **A reviewer challenged
the floor after these results were seen, and the declared range was
widened to e ∈ [0.2, 0.95] in response — a post-hoc extension, stated
rather than slipped.** No new holdout access was needed or taken: the
sweep runs on the committed Stage-7 replay artifact
(`holdout_replay.parquet`), and its e ≥ 0.6 slice reproduces the
logged-access grid **exactly** (max deviation 0.0 —
`e_sweep_summary.json`). Same construction: validation-tuned fixed
threshold per corner, both systems evaluated on holdout rows, 400
bootstrap resamples; 27 (m, a, c_h) corners per e level:

| e | corners with CI > 0 | median edge | weakest corner (point) |
|---|---|---|---|
| 0.95 | 27/27 | +22.0% | +13.4% |
| 0.775 | 27/27 | +14.2% | +6.8% |
| 0.60 | 27/27 | +8.4% | +3.4% |
| **0.50** | **27/27** | **+5.8%** | **+2.1%** |
| 0.40 | 23/27 | +3.6% | +0.7% |
| 0.30 | 16/27 | +1.7% | +0.4% |
| 0.20 | 13/27 | +1.0% | **−0.1%** |

**The breaking point of the uniform claim is e\* = 0.5**: unanimity —
every corner's CI excluding zero — holds down to a step-up that stops
only half of fraud, and fails below it, corner by corner (23/27 at
e = 0.4, 13/27 at e = 0.2, where the weakest corner's point estimate
turns negative). The *median* edge never breaks anywhere in [0.2, 0.95].
That is the expected signature of the decomposition above: as e falls,
step-up stops paying, the policy converges to the threshold it is being
compared against, and the edge goes to zero from above.

## Prediction scorecard for this access

- Rank-by-amount: direction held (never beats shipped at any budget),
  magnitude **missed** — it is a far stronger loss-weighted baseline
  than we called (0.34 vs called 0.05–0.20; margin 1.37× vs called ≥2×).
- Random floor: **hit**.
- Maturity sweep: no-reversal **hit**; 30-day delta and lane-1 size each
  land just outside the called band (one high, one low).
- Cost rebuild: k and median both **missed favourably** (81/81 vs called
  35–65; +14.4% vs called +1–4%).

Which unfavourable-if-true results came back unfavourable: the
rank-by-amount finding. It goes in the README, not a footnote: a
no-model amount sort captures 73% of our loss-weighted headline at the
primary budget. The corrected metric family (unweighted first-hit
recall, precision, budget-matched FPs) is where the system actually
earns its keep, the README leads with it, and loss-weighted figures are
now reported only with the rank-by-amount row beside them.

## On the 8-minute gap

The pre-registration commit (67d35f7) landed 8 minutes before the
unsealing, which could look thin. The defense is the one thing that
cannot be forged after the fact: the pre-registration contains a numeric
prediction that missed badly in the unfavourable direction —
rank-by-amount called at 0.05–0.20, landed at 0.3447. Nobody
reverse-engineers a pre-registration that makes themselves look wrong.
