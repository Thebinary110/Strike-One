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

**Prediction: MISSED on magnitude, held on direction.** We predicted
rank-by-amount's loss-weighted first-hit recall in 0.05–0.20 and a ≥2×
margin for the shipped system. Actual: **0.3447**, margin **1.37×**.
Fraud amounts on this data are top-heavy enough that ranking by amount
alone — no model — recovers 73% of the shipped system's loss-weighted
number at the primary budget, while being useless on every unweighted
metric (5.3% of cases caught first-hit, 5.5% precision, 3,023 angry good
customers). The shipped system stays ahead on loss-weighted recall at
every budget in the grid (1.26×–1.83×), but the honest sentence is:
**if your only objective were loss-weighted coverage and you tolerated
~95% false positives, a sort-by-amount would get you most of the way.**
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
guess. Two honest readings of why the edge is that large: (a) most of it
is the step-up action existing at all — a two-action threshold must buy
fraud protection with hard blocks of good customers, while step-up
prices the middle; (b) the counterfactual assumption feeds it directly:
**a blocked fraudulent transaction is assumed fully avoided, and a
stepped-up one avoided with probability e**. That assumption is not
measurable in this data; its sensitivity is the e dimension (and the s
liability-shift dimension) of the declared grid, and the +3.4% weakest
corner is where those assumptions are least favourable. No single-point
cost figure is stated, here or anywhere.

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
earns its keep, and the README says so.
