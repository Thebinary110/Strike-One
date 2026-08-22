# Stage 6 — The product surface

## Surprises first

1. **The console made the model war look like a sideshow — the routing is
   the product.** With routing ON, the two scorers are within ±0.01
   first-strike recall of each other across the *entire* capacity range
   (at 18 alerts/day: shipped 0.249 vs headline-B 0.250). The whole
   tight-budget catastrophe is one configuration: `headline + routing
   OFF` (0.081 at 18/day — 3.1× below anything routed). A2's +0.018 edge
   at the primary budget is real and CI-backed, but next to the routing
   effect it is visually invisible. Full curves in `/api/curve`; detail
   below.
2. **The replay build caught one more bug before it could bite**: the
   prep script initially refit A2 with the bookkeeping `uid` column
   accidentally included as a 43k-category feature (scores diverged from
   the frozen system by up to 0.67). Root cause was mine, not LightGBM
   nondeterminism; fixed by predicting with the **hash-verified frozen
   booster** instead of any refit — which is the more defensible design
   anyway (the shipped system is the artifact, not a recipe re-run).
3. At the default operating point our lane-2 alerts spend **more on false
   positives (1,602) than on redundancy (571)** — the honest-costs line
   makes that stark on screen, and it is the right thing for a viewer to
   see first.

## What was built

One tool, three controls, every control demonstrating a measured finding
(`uv run python -m strikeone.console`, stdlib HTTP server + one static
page; no auth, no database, no cloud, no new dependencies):

- **Control 1 — capacity slider** (5–500 alerts/day, default **100**,
  labelled "stated review-capacity assumption" on screen). Default is our
  *weakest* operating point; tightening the slider lets the viewer
  discover the divergence themselves. A small context strip under the
  slider draws first-strike recall vs capacity for the current
  configuration against its natural comparison.
- **Control 2 — scorer selector**: shipped (two-lane + A2) / headline
  pick (B, AP 0.748) / blocklist-only (no model; natural operating point,
  slider disabled).
- **Control 3 — routing toggle**, applied to whichever scorer is
  selected. Turning routing OFF under B at 18/day shows 0.250 → 0.081
  live; ON again triples it back. This is the named routing-inoculation
  result, watchable.

**The two counters, live** (recomputed server-side from the loaded replay
on every control change): "Episodes stopped at strike one — N of 1,040"
and "Alerts spent re-flagging entities already known bad — N", with the
standing sub-line "1,711 known-bad entities handled by the blocklist
lane — zero alerts consumed".

**Honest costs, same screen, not a footnote**: false positives at the
current budget (1,602 for ours at the default vs 890 for B at 2,810 —
shown, owned, with the on-screen statement that an FP frictions a good
customer *and* costs analyst time, strictly worse per unit than a
redundant alert); plus the standing lane-1 policy's **783 blocked
legitimate transactions**, counted on screen and logged as future work
(step-up instead of hard block for known-bad entities — the model is
frozen, so a note, not a change).

**Entity timeline**: any decision-stream row (or the "show a real
episode" button) renders the entity's transaction history — amount vs
day, STRIKE ONE lit in red and labelled, propagated positives in orange,
interventions ringed. Designed as the screenshot.

**Decision stream**: chronological replay of the shipped system's
decisions (day, amount, lane, calibrated p, action, ground-truth role
marked as an evaluation-only overlay).

**Scoring service**: `GET /api/score?tid=…` returns the full decision
object — calibrated probability, lane, point-in-time entity state
(`no prior flags` / `already flagged`), chosen action, the three-way
expected-cost arithmetic behind it, and the ground-truth episode role
explicitly labelled EVALUATION_ONLY.

## Latency (commodity CPU, single-row path single-threaded)

| Path | p50 | p99 |
|---|---:|---:|
| feature path (time features, category map, UID + blocklist KV lookup) | 2.90 ms | 3.01 ms |
| model inference (frozen A2 booster, 1 row) | 4.65 ms | 4.84 ms |
| decision (isotonic + argmin) | 0.02 ms | 0.03 ms |
| **total** | | **7.84 ms** |

Batch throughput: **577k rows/s**. Inference dominates — the calibration
note anticipated that this usually signals features precomputed in a way
production couldn't reproduce. Here it is the opposite and it is a
product point: **the corrected metric selected a scorer with no entity
aggregates, so the only online state a deployment needs is a blocklist
key-value set.** Nothing was precomputed away; the measured feature path
is mostly 1-row pandas overhead.

## Engineering constraints, verified

- **Validation data only**; the holdout access log is asserted empty at
  the end of every script and at console startup (still zero entries).
- **Nothing hardcoded — verified by slice swap**: rebuilt the replay for
  days 120–133 only and pointed the console at it; every number
  recomputed (14 days, 566 episodes, lane-1 928, different counters).
  Stage 7 will point `--data` at a holdout-derived file the same way.
- **The console is not where numbers get chosen**: scores come from the
  hash-verified frozen booster, calibration from the frozen isotonic
  breakpoints, params from `shipped_system_frozen.json`; the UI holds no
  constants.
- **One command**: `uv run python -m strikeone.console` (prerequisites
  are earlier stage scripts, documented in the README repro chain).
  6 unit tests cover the counter logic on a synthetic slice (39 total).
- Restraint: two counters, one timeline, one stream, three controls, one
  slider context strip. No other charts.
- Visual rendering was verified at the API level and by static review;
  browser screenshotting was unavailable in this environment, so the
  one-look visual check is the human's (`uv run python -m
  strikeone.console` → http://127.0.0.1:8777).

## Gate checklist

- [x] Three controls working, counters live off the slider
- [x] FP and lane-1 legit-block counts on the main screen
- [x] Entity timeline screenshot-ready (STRIKE ONE labelled, propagated
      distinguished, interventions ringed)
- [x] Scoring service returns the full decision object
- [x] Latency reported split (feature vs inference vs decision), with the
      honest reading of why inference dominates
- [x] One-command startup; slice-swap verification done
- [x] Holdout log still empty
