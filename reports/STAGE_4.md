# Stage 4 — Decision engine, and the honest price of the metric choice

## Surprises first

1. **The budget-matched check (verification 1) retired our best sentence.**
   At the blocklist's own N=1,711, Baseline A's precision is **73.1%**,
   not the 54.4% we had quoted from an unmatched budget. The corrected
   headline is stronger anyway: blocklist 54.2% precision / **zero** first
   strikes; A at the same budget 73.1% / 525 first strikes; **B at the
   same budget 90.5% precision with *lower* first-strike recall than A
   (0.397 vs 0.505) — precision rising as prevention falls, in one row.**
   STAGE_3.md corrected in place.
2. **The money slide inverted — twice — and the honest version is better
   than the planned one.** Under naive realized cost, the headline pick
   (calibrated B) is *cheaper* than our system in most of the grid: naive
   cost accounting credits propagated catches exactly as AP does. Under
   corrected **episode-aware** accounting (an entity is stopped at its
   first block; downstream fraud after that is prevented; catching fraud
   #3 does not un-lose #1–2), ours wins **33% of the grid**, B the rest;
   at the central point B is cheaper by 41.8 per 1,000 transactions =
   **0.031% of processed volume**. The defensible claim that emerges:
   **+0.17 AP — the improvement the standard metric screams about —
   prices out to ±0.03–0.14% of volume with a sign that flips across a
   reasonable cost grid.** The metric distortion doesn't show up as money
   at the unconstrained cost optimum (both systems intervene broadly and
   converge on first strikes); it shows up under **capacity constraints**
   (2.7× first-strike difference at 500 alerts) and in **what the system
   is**: an auditable blocklist lane plus a prevention model, versus a
   model that re-derives a worse blocklist implicitly.
3. **The predicted amount-dependence headroom did not materialise.** The
   3-action argmin beats the best *2-action fixed threshold* everywhere
   (2.2–12.7% of trivial cost — that is the step-up action's value), but
   beats the *amount-blind 3-action* comparator in only 68% of corners
   with a central gap of 0.04% — and loses to it by up to 1.3% in some.
   The loss-weighted-recall skew exists at the ranking level, but with
   all three cost branches scaling with A (only c_h is fixed), the
   argmin's decisions are nearly amount-invariant. Negative finding,
   reported as such.
4. **The lane-2 retrain is a real, CI-backed modelling win** (the gate's
   "experiment I most want run"): see B below.
5. **Zero first strikes land in lane 1** — the routing rule loses nothing
   by construction on this data (the pooled-entity concern did not
   materialise).
6. **Two-lane routing fixes B's tight-budget collapse for free**: B's
   first-strike recall at budget 500 is 0.079 single-lane but 0.246 when
   restricted to lane-2 rows — the routing inoculates *any* scorer
   against the redundancy trap.

## Verifications from the Stage 3 gate

1. **Budget-matched blocklist** — done, above; reports corrected.
2. **CI on the card1+email flip**: +0.0269 [−0.0062, +0.0604], p = 0.073
   (cluster bootstrap by that key). Not significant; STAGE_3.md updated.
3. **Novelty denominators**: 158,106 of 163,892 known UIDs were clean
   through day 119; 18,483 of those transacted in validation; **13 struck
   — onset rate 0.07%, vs 4.22% for the 24,325 novel UIDs (60×)**. The
   definitional coupling is stated and the finding survives it.
4. **Fallback stratum**: fraud rate **12.9% (val) / 10.9% (train) vs
   ~2.45% for resolved entities**; hosts 487 of 1,026 attributable first
   strikes on 10.2% of rows. A missing billing address is itself a strong
   signal; recorded as a policy segment for future work (the shipped
   policy treats it through the model's addr1-null visibility rather than
   a separate lane — one moving part fewer).

## A. Two-lane vs single-lane — measured, both accountings

Lane 1 := uid has a known fraud ≥ 7 days old → block by rule (1,711 val
rows; 2.1% of rows, **33.0% of positives**). Lane 2 := everything else →
calibrated score → cost-derived action.

**Model-friction accounting** (lane-1 blocks are the standing blocklist,
not model alerts — the deployment reality): at 2,810 model alerts, the
two-lane system catches 628 first strikes (60.4% of episodes) vs 574
(55.2%) for single-lane B at the same model-alert count, while covering
72.5% of propagated fraud (lane-1 free coverage + lane-2).

**Total-intervention parity accounting** (every block counted, the harder
test — `two_lane_vs_single.csv`): at small totals the two-lane system's
FS recall is *worse* (lane-1's 1,711 unrankable blocks eat the budget);
parity is reached around T=6,000. Stated plainly: **the two-lane design
wins under the deployment framing and loses under strict parity at tight
totals** — its justification is the deployment reality (a blocklist runs
anyway, is automated, and does not consume analyst alerts) plus the
episode-aware economics, not parity arithmetic.

The anticipated attack — "you hard-coded the propagation rule" — is
answered directly: yes, deliberately. A real risk stack blocklists
confirmed-fraud entities; doing it explicitly, at zero model friction, is
what lets the model be evaluated on what it uniquely contributes.

## B. Lane-2 retrain (A2) — shipped

A2 = Baseline A's exact recipe trained on lane-2-eligible train rows only
(the population lane 2 actually scores; flagged-entity rows carry a
near-deterministic label the lane-2 model never sees in deployment).

| Metric (lane-2 val rows) | A | A2 | paired Δ |
|---|---|---|---|
| FS recall @2810 | 0.586 | **0.604** | **+0.0183 [+0.0068, +0.0297]**, p=0.002 |
| AP | 0.574 | 0.588 | +0.0139 [+0.0079, +0.0205] |
| ROC-AUC | 0.923 | 0.942 | — |

Small positive, CI excludes zero, no alarm triggers (lane-2 AP < 0.65).
Leakage audit: the eligibility filter uses only information available at
each row's time (the same 7-day-delayed flag that routes in deployment),
and A2's features contain no entity/label aggregates at all.

## C. Model selection, made formally

Pre-stated rule: A2 ships iff its paired FS-recall delta over A at the
primary budget excludes zero in its favour. It does (+0.0183 [+0.0068,
+0.0297]). **Selected: A2.**

**Stated plainly: headline AP selects B (0.748 vs 0.573 full-val); the
corrected yardstick — first-strike recall and friction efficiency on the
lane-2 population — selects two-lane + A2. These are different systems.**
(Full curve: `model_selection_curve.csv`. B is competitive on lane-2 FS
at loose budgets — the routing salvages it — but A2 leads at and above
the primary budget and ships on the pre-stated rule.)

## D. Calibration, cost policy, sensitivity

- **Calibration** (lane-2 val, in-sample for Stage 4 reporting; the
  Stage 7 secondary refit uses the locked nested split): Brier — raw
  0.01402, **isotonic 0.01382 (chosen)**, Platt 0.01401. Reliability
  curves: `fig_reliability.png`.
- **Cost parameters, declared ranges**: m ∈ [0.05, 0.25], a ∈ [0.05,
  0.20], e ∈ [0.60, 0.95], c_h ∈ [15, 60] amount-units (card-network
  chargeback fees are commonly $15–50 per dispute in public sources, and
  this dataset's amounts are dollar-scale, median 68). Central: m=0.15,
  a=0.125, e=0.775, c_h=30. All economics in dataset amount units and %
  of volume; **no INR conversion is asserted**.
- **The policy beats both trivial baselines across the entire declared
  grid**: savings vs the cheaper of approve-all/block-all = **61.7% to
  93.3%** (81/81 corners; original brief's gate condition met). Central
  action mix: approve 82.7%, step-up 15.4%, block 1.8%.
- **Vs fixed thresholds**: beats the best 2-action threshold in **81/81
  corners** (worst corner: m=0.15, a=0.20, e=0.60, c_h=30 — still +2.2%
  of trivial cost). Beats amount-blind 3-action in only 55/81 — the
  amount-dependence null of surprise 3.
- **Review queue** (outside the argmin, capacity stated): at 5/20/50
  reviews/day, queue precision 23.6%/20.4%/15.0%, Card Precision@k
  0.336/0.270/0.215, first-strike catches 6/34/80
  (`review_queue.csv`).

## E. Pricing the metric choice (episode-aware, the honest version)

Episode-aware accounting (entity stopped at first block; conservative,
symmetric simplification: step-up does not stop an episode). Central
costs on validation (amount units):

| System | Episode-aware cost |
|---|---:|
| approve-all | 557,056 |
| blocklist-only | 368,102 |
| single-lane A | 180,354 |
| **two-lane + A2 (ours)** | **139,458** |
| single-lane B (headline pick) | 136,119 |

- **The architecture + retrain is worth 22.7% of cost vs single-lane A**
  (180k → 139k) — the corrected-metric path, engineered properly, closes
  essentially all of B's naive advantage.
- **Ours vs B: ±0.03–0.14% of volume, sign varying** — ours wins 27/81
  corners, concentrated at low margin m (70% win rate at m=0.05) and low
  step-up efficacy e (56% at e=0.60); B wins where margins are high and
  step-up nearly perfect. **Named vanishing/worst corner: m=0.25, a=0.20,
  e=0.95, c_h=60** (B cheaper by 186.9/1k = 0.139% of volume). c_h does
  not affect the winner at all.
- The limitation slide writes itself: **if step-up is cheap and nearly
  always defeats fraud, broadly step-upping everything the transaction
  metric flags is a fine policy, and the metric choice stops mattering
  economically.** Where step-up is imperfect or margins thin — arguably
  the common case — episode-aware selection wins.
- Full grids: `sensitivity_grid.csv` (naive), `episode_cost_grid.csv`
  (episode-aware).

## F. Freeze (shipped system)

`shipped_system_frozen.json`, config hash
**b632a136a43e5d610901ac5bd24be402914ca3c28ec06a584e7c15a78ee0d9b3**:
routing rule, lane-2 scorer = A2 (model file SHA-256 inside), isotonic
calibration map (serialized breakpoints), central cost params + declared
ranges, review-capacity assumptions, and the pre-stated selection rule
with its evidence. Stage 5, if it happens, is ablation-only and cannot
enter this system. The Stage 7 protocol (primary frozen day-112 /
secondary refit-through-147 with nested calibration) was locked earlier in
`holdout_prediction.md`.

## Holdout status

Access log verified empty (zero entries) at the end of every Stage 4
script.
