# Canonical comparison table

Every public figure, with its exact contrast, operating point, and data
slice. All rows are HOLDOUT (days 151–182, sealed; two logged accesses,
each against a pre-registered plan committed beforehand) unless marked.
Any figure quoted anywhere — video, README, panel Q&A — must match a row
here verbatim. C1–C8 are from the first access (Stage 7, commit 188b471);
C9–C12 from the second (commit 67d35f7, `reports/stage8/`).

| ID | Contrast (exact) | Operating point | Figure | Source |
|---|---|---|---|---|
| C1 | Three systems: transaction precision & first-strike catches — blocklist / single-lane A / single-lane B | N = 1,775 alerts (the blocklist's natural operating point) | 0.498 & **0** · 0.699 & **566** · 0.891 & **442** | `reports/stage7/results.json` item3 |
| C2 | **Model** contrast: B − A, transaction-level AP (the distortion) | all 92,427 holdout rows | **+0.1768** [+0.1643, +0.1887] | item2 |
| C3 | **Model** contrast: B − A, first-strike recall, both single-lane | 3,200 alerts (100/day × 32d) | **−0.0192** [−0.0326, −0.0052] | item5 |
| C3v | same contrast, VALIDATION (the two-period replication) | 2,810 alerts (100/day × 28d) | −0.0163 [−0.0307, −0.0027] | `reports/stage3/episode_analysis.json` |
| C4 | **Routing** contrast: B with vs without the blocklist lane, first-strike recall (inoculation) | 576 alerts (18/day × 32d) | 0.0977 → 0.2262 = **2.32×** | item4 / `capacity_curves.csv` |
| C4v | same contrast, VALIDATION | 504 alerts (18/day × 28d) | 0.0808 → 0.250 = 3.1× | stage6 curve |
| C5 | **System** contrast: shipped two-lane+A2 vs single-lane B — the two counters | 3,200 model alerts each | stopped at strike one **698 vs 643** (of 1,198); re-flagging known-bad **692 vs 1,425** | item5 / `episode_table.csv` |
| C6 | Primary (frozen d112) vs secondary (refit d147, nested calibration): AP | all holdout rows | 0.5319 [0.5167, 0.5504] → 0.6001 [0.5843, 0.6176] = **+0.068** | items 1, 7 |
| C7 | Shipped system honest costs | 3,200 alerts (100/day) | precision **0.434**, false positives **1,810**, lane-1 legitimate blocks **891** | item5 |
| C8 | Headline AUCs, context for the ceiling note | all holdout rows | A 0.9033 · B 0.9544 (vs winner's private 0.9459 — B holds delayed labels no entrant had) | items 1, 2 |
| C9 | **Baseline** contrast: rank-by-amount (no model) vs shipped two-lane+A2, LOSS-WEIGHTED first-hit recall | 3,200 alerts (100/day) | **0.3447 vs 0.4733** (ratio 1.37×; we predicted ≥2× — prediction missed, direction held). Rank-by-amount's unweighted numbers: 5.3% first-hit recall, 5.5% precision, 3,023 FPs | `reports/stage8/baselines_kcurve.csv` |
| C10 | **Floor** contrast: random ranking, all metrics | 3,200 alerts (100/day) | first-hit recall 3.8%, loss-weighted 3.4%, precision 3.4% (≈ budget share, as predicted) | same |
| C11 | **Robustness**: label-maturity sweep, shipped − B first-hit recall delta (uid-cluster CI), evaluation-side only | 3,200 alerts; delay 1→30 days | +0.0543 [+0.041, +0.068] at 1d → **+0.0434 [+0.031, +0.057] at 30d**; positive with CI excluding zero at every delay in {1,3,7,14,30}; no reversal, no boundary to name | `reports/stage8/maturity_sweep.csv` |
| C12 | **Cost** (rebuilt, replaces the withdrawn same-data "81/81"): frozen validation-fitted policy vs per-corner validation-tuned fixed threshold, both evaluated on holdout, per-corner row-bootstrap CIs | 81 corners (s=0 grid) | **81 of 81 CIs exclude zero**; median edge **+14.4%** of approve-all cost, IQR [+9.3%, +20.5%], weakest corner +3.4%. Assumes a blocked fraud is fully avoided and a stepped-up one avoided with probability e; that assumption's sensitivity is the e (and s) grid dimension | `reports/stage8/cost_rebuild_grid.csv` |

**Do not conflate:** C3 (−0.0192) is a *model* comparison, single-lane vs
single-lane. C5 (698 vs 643) is a *system* comparison, two-lane vs
single-lane. C4 (2.32×) is a *routing* comparison on one fixed scorer.
Three different contrasts; three different numbers; never mixed in one
sentence.

**A numeric collision, documented so nobody infers a link:** the
standalone-window audit (`strikeone audit --example ieee-cis`, the README
hero) reports **733** blocklist-coverable alerts for the bare A2 scorer at 100/day
within its own window. C5 above also contains a **733** (the
between-systems difference in blocklist-coverable alerts, 1,425 vs 692). These are
unrelated quantities that happen to coincide numerically.
