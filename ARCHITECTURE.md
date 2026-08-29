# Architecture

## The shipped system (frozen at Stage 4, config hash `b632a136…`)

```
incoming transaction
        │
        ▼
  UID = card1_addr1_floor(day−D1)      (nulls pooled as literal "nan")
        │
        ▼
  blocklist KV lookup ──────────────► LANE 1: entity has a known fraud
        │  (the system's ONLY               ≥ 7 days old → BLOCK by rule.
        │   online state)                   Zero model friction,
        │                                   no alert consumed.
        ▼
  LANE 2: no prior flags
        │
        ├─ features: raw transaction + identity columns + cyclical
        │  time-of-day / day-of-week. NO entity aggregates, NO online
        │  feature store. (The corrected metric selected this.)
        ▼
  A2 (LightGBM, trained on lane-2-eligible rows only)   ~4.8 ms p99
        │
        ▼
  isotonic calibration (frozen breakpoints)              ~µs
        │
        ▼
  3-action expected-cost argmin over {approve, step-up, block}
  with declared cost ranges m/a/e/c_h                    ~µs
        │
        ▼
  decision object: p, lane, entity state, action, cost arithmetic
```

Total p99 ≈ 7.8 ms/transaction on a laptop CPU; 577k rows/s batched.
Manual review is a capacity-bounded top-k queue ranked by expected loss,
outside the argmin.

## Evaluation machinery (what makes the numbers trustworthy)

- **Chronological splits only** (days 1–112 train / 113–119 delay gap /
  120–147 validation / 148–150 blind gap / 151–182 holdout), day indices
  only, never calendar dates.
- **Sealed holdout**: own parquet, SHA-256 committed, loadable only via
  `strikeone.seal.load_holdout(unseal=True, reason=…)`, every access
  appended to a committed log. Opened exactly once, at Stage 7, against a
  pre-registered analysis plan.
- **Point-in-time features** (`strikeone/entity.py`): expanding/windowed
  aggregates over strictly-prior rows; label-derived features additionally
  lagged by the 7-day verification delay. Unit-tested against
  hand-computed examples, including cross-entity bleed and tie-breaking.
- **Episode roles** (`strikeone/episodes.py`): first strike vs propagated,
  assigned on the global chronological stream, never per slice; null
  entity ids are refused (a regression test guards the pandas-3 bug this
  once caused).
- **Friction accounting** (`strikeone/metrics.py` + `episodes.py`):
  first-strike catches / redundant / false positives per intervention,
  friction efficiency, redundancy rate, loss-weighted first-strike recall,
  (cluster-)bootstrap CIs and paired deltas.

## Repository layout

```
src/strikeone/
  config.py       paths, split boundaries, seeds, delay constant
  data.py         ingest + verify (3 fingerprints), join, day index
  seal.py         holdout sealing, hash check, access log
  features.py     baseline feature hygiene (exclusions documented)
  entity.py       point-in-time entity machinery + UID recipe
  episodes.py     episode roles + friction accounting
  metrics.py      headline metrics, cost model, bootstrap
  console.py      scoring service + live-counter console (stdlib HTTP)
  console_static/ the one-page UI
scripts/          one entry point per stage (stage0_build … stage7_run)
reports/          STAGE_N.md per stage + committed result artifacts
  holdout_prediction.md   pre-registered ranges, analysis plan, policy
  holdout_access.log      committed; exactly one entry after Stage 7
PROPOSALS.md      every judgment call outside the brief, with status
```

## Frozen artifacts

| Artifact | Where | Integrity |
|---|---|---|
| Baseline A model | `models/baseline_a.txt` (gitignored, rebuildable) | sha256 in `reports/stage1/baseline_a_frozen.json`, config hash `904a84eb…` |
| Lane-2 scorer A2 | `models/lane2_a2.txt` | sha256 inside `reports/stage4/shipped_system_frozen.json` (`b632a136…`) |
| Calibration map | isotonic breakpoints serialized in the frozen JSON | part of the config hash |
| Cost params | central + declared ranges in the frozen JSON | part of the config hash |
| Holdout | `data/processed/holdout.parquet` | sha256 in `data/holdout.sha256`; access log `reports/holdout_access.log` |
| Raw data | `data/raw/*.csv` (never committed) | sha256 in `data/raw_checksums.sha256` + 3 load-time fingerprints |

The console displays no constant of its own: every figure is computed at
request time from a replay parquet plus the frozen JSON, which is what
allows Stage 7 to re-point it at the holdout unchanged.
