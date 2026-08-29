# Stage 7 — The holdout, opened once

The seal was broken exactly once, by `scripts/stage7_run.py`, against the
pre-registered analysis plan committed beforehand (`holdout_prediction.md`,
commit 188b471). The access log (`reports/holdout_access.log`) holds
exactly one entry, hash-verified. Every figure below was named in the plan
before any holdout number was seen; nothing was added or dropped after.

Holdout: 92,427 rows over 32 days, 3,213 positives, **1,198 first-strike
episodes**, lane-1 (known fraud ≥7d old) 1,775 rows. Row and positive
counts match the Stage 0 committed slice table exactly.

## Prediction scorecard — 6 hits, 3 misses, misses first

| Quantity | Predicted | Actual | Verdict |
|---|---|---|---|
| Primary A, AP | [0.32, 0.48] | **0.5319** [0.5167, 0.5504] | **MISS (high)** |
| B−A AP gap (distortion) | +0.06 … +0.14 | **+0.1768** [+0.1643, +0.1887] | **MISS (high)** |
| Propagated share of positives | 45–60% (falling) | **62.7%** (val: 63.0%) | **MISS (premise)** |
| Primary A, ROC-AUC | [0.86, 0.91] | 0.9033 [0.8972, 0.9099] | hit |
| Routing ratio @18/day | 1.5–2.8× (narrowing from 3.1×) | **2.32×** | hit |
| Lane-1 row share | 1.2–2.0% (below val 2.14%) | 1.92% | hit |
| Lane-1 positive share | 18–30% (below val 33.0%) | 27.5% | hit |
| Secondary A, AP | [0.50, 0.62] | 0.6001 [0.5843, 0.6176] | hit |
| Secondary A, ROC-AUC | [0.90, 0.93] | 0.9239 | hit |

### The misses, read honestly

- **Primary AP missed high**: the frozen day-112 model aged far better
  than the validation-tail extrapolation implied (0.5734 → 0.5319, a
  −0.042 drop, vs the ~0.40 forecast). Integrity was checked before the
  number was believed: the unseal verified the committed SHA-256,
  row/positive counts match the Stage 0 table exactly, and every booster's
  feature list was asserted against its frozen artifact. No unregistered
  diagnostics were computed (plan discipline); the residual explanation is
  that the decay floor from time-stable features sits near 0.53, and the
  late-validation weeks we extrapolated from were a local dip plus a
  compositional tailwind we underweighted (holdout identity coverage
  21.0% vs validation 17.7%). A drop is present and healthy — AUC fell
  0.9184 → 0.9033, closely mirroring the competition winner's public →
  private −2.2 AUC points.
- **The distortion did not weaken, and the reason is the third miss**: we
  predicted the propagated share of positives would fall with the higher
  entity novelty; it stayed flat (62.7% vs 63.0%), because propagation
  regenerates *within* the window — episodes that start in the holdout
  propagate inside its own 32 days. With the propagated share flat, the
  distortion stayed flat (+0.174 val → +0.177 holdout). **The forecast of
  the input variable was wrong; the mechanism — distortion scales with
  propagated share — behaved exactly as claimed.** The routing prediction,
  whose premise (lane-1 coverage) *did* move as forecast, hit its range.
- **One number above the sanity ceiling, explained rather than excused**:
  B posts holdout AUC **0.9544**, above the ~0.95 bug-report line and the
  competition winner's private 0.9459. This is not treated as a leak
  because B has an information source no competition entrant had —
  actual labels ≥7 days old *inside the evaluation window* (the
  brief-sanctioned delayed-label features). A model with blocklist-echo
  features beating the competition ceiling is the thesis, not a bug; the
  ceiling applies to competition-comparable models, and A sits at 0.9033.

## The pre-registered results, in plan order

1. **Primary A**: AP 0.5319 [0.5167, 0.5504] (above range), AUC 0.9033
   [0.8972, 0.9099] (in range).
2. **Distortion**: B AP 0.7088, AUC 0.9544; **B−A = +0.1768 [+0.1643,
   +0.1887]** — the headline metric still screams.
3. **The inversion, at the blocklist's natural N=1,775** — the trend
   survives intact:

   | System | txn precision | first-strike catches |
   |---|---:|---:|
   | blocklist | 0.498 | **0** |
   | A | 0.699 | **566** |
   | B | **0.891** | 442 |

   Precision rises as prevention falls, on out-of-time data.
4. **Routing inoculation @18/day (576 alerts)**: B unrouted 0.098 → routed
   0.226, **2.32×**, in the predicted range.
5. **Episode table @100/day (3,200 alerts)** — the two counters:

   | System | FS catches | redundant | FP | FS recall | friction eff | redundancy | precision |
   |---|---:|---:|---:|---:|---:|---:|---:|
   | **two-lane+A2 (shipped)** | **698** | **692** | 1,810 | **0.5826** | 0.2181 | 0.4978 | 0.434 |
   | single-lane B | 643 | 1,425 | 1,132 | 0.5367 | 0.2009 | 0.6891 | 0.646 |
   | single-lane A | 666 | 953 | 1,581 | 0.5559 | 0.2081 | 0.5886 | 0.506 |
   | blocklist | 0 | 884 | 891 | 0 | 0 | 1.000 | 0.498 |

   **Counters: "Episodes stopped at strike one: 698 of 1,198" vs "Alerts
   spent re-flagging known-bad entities: 692"** (single-lane B: 643 and
   1,425), with lane-1 handling 1,775 known-bad entities for free (891
   legitimate transactions blocked by the standing policy — shown, owned).
   **B−A first-strike delta on holdout: −0.0192 [−0.0326, −0.0052] — B is
   again significantly worse at prevention while winning every headline.**
   The console, pointed at `holdout_replay.parquet`, reproduces these
   counters exactly (the Stage 6 slice-swap path, used as designed).
6. **Capacity curves** committed (`stage7/capacity_curves.csv`); shape as
   on validation: routed configurations converge, unrouted B collapses as
   budgets tighten.
7. **Secondary (refit through day 147, nested calibration)**: AP 0.6001
   [0.5843, 0.6176], AUC 0.9239 — both in range. **The price of
   retraining cadence: +0.0682 AP** (predicted +0.1–0.2; the real value is
   smaller because the primary aged better than feared). Secondary
   two-lane counters @100/day: 712 stopped at strike one (59.4%), 718 on
   known-bad.
8. **Loss-weighted first-strike recall (shipped @100/day): 0.4733** (val
   0.415) — the amount skew did not worsen out-of-time.

## Repo finish

- Clean-clone reproduction verified: fresh `git clone`, checksum-verified
  raw data, `uv sync`, 39/39 tests, `stage0_build` reproduced the sealed
  holdout **byte-identically** (same SHA-256) with an empty log.
- `reports/holdout_access.log`: exactly one entry, pointed to from the
  README.
- README reordered limitations-first per the locked structure; "Why no
  graph model" and "Bugs our own checks caught" sections in place;
  `ARCHITECTURE.md` added.
- Every correction banner intact; originals in git history.
