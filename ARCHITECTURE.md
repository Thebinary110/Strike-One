# Architecture

Strike One ships two things: a **bring-your-own-scorer evaluation
package** (`strikeone` — audit / route / policy / check / tui), and the
**reference detector** that package's corrected evaluation selected on
IEEE-CIS, frozen before the sealed holdout was opened. The reference
detector is the measured subject of the study, not a model to deploy on
your traffic; the package is the part meant to run on yours. (An earlier
video walkthrough referenced here was removed from the repo; `FINDINGS.md`
is the narrative now.) The cost ranges below include the liability-shift
parameter `s` (default 0, freeze-preserving).

## The reference detector (frozen at Stage 4, config hash `b632a136…`)

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
  with declared cost ranges m/a/e/c_h/s                    ~µs
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
  appended to a committed log. Two accesses, each against a
  pre-registered plan committed beforehand (Stage 7; then baselines and
  robustness checks, `reports/stage8/`).
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
  audit.py        the corrected evaluation (the product's face)
  route.py        two-lane routing around any scorer
  policy_engine.py cost-derived actions in declared ranges
  cli.py / rpc.py the command line and the TUI's stdio backend
  ai/             optional narration layer, off by default: evidence
                  contract (versioned+hashed), citation validator
                  (fail-closed), Ollama + OpenAI-compatible adapters.
                  The model narrates finished evidence; it never
                  computes, routes, or touches the holdout.
scripts/          one entry point per stage (stage0_build … stage7_run)
reports/          STAGE_N.md per stage + committed result artifacts
  holdout_prediction.md   pre-registered ranges, analysis plan, policy
  holdout_access.log      committed; exactly two entries, both pre-registered
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

Every surface (CLI, TUI, the legacy console in extras/) displays no
constant of its own: figures are computed at request time from a replay
parquet plus the frozen JSON, which is what allowed Stage 7 to re-point
the tooling at the holdout unchanged.
