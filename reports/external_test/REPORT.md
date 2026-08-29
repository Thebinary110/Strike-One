# Third-party test report: Strike One on a foreign dataset

> **Terminology revision (2026-08-30).** Later review standardised the
> project's vocabulary: what this report calls "wasted" / "redundant"
> alerts are now "blocklist-coverable" (alerts a standing blocklist would
> also have covered), "first strike / first attempt" is "first hit / the
> case's first labelled transaction", and causal phrasings such as
> "prevented a loss" are replaced by "caught at the case's first labelled
> transaction". This report keeps its original wording; rewriting history
> silently would undercut the integrity story it documents.

Role-played as an outside tester with no codebase knowledge beyond the
README and `examples/`. Goal: plug in a dataset the authors never touched,
bring my own scorer (the product's premise), generate results, and try to
break things. Fix commits landed after the findings were filed; findings
are listed as found.

## Dataset

Sparkov credit-card simulation via HuggingFace
(`Nooha/cc_fraud_detection_dataset`, part 0): **1,323,347 transactions,
1,095 days, 470 card entities, 4,420 fraud rows (0.33%)**. Fully synthetic
(generated identities), publicly hosted, nothing vendored into this repo;
only our outputs are committed here. Shape: `trans_num`, `unix_time`
(epoch seconds), `amt`, `cc_num` (entity), `is_fraud`, plus demographics.
Structurally nothing like IEEE-CIS: 3-year window, few entities with long
histories, sub-percent fraud.

## What worked (the product claims, verified by an outsider)

1. **Onboarding**: `check` with five `--map` pairs and `--save-config` was
   the entire integration. Wrong column names produce the available-column
   list; no-mapping produces a copy-pasteable example. No code written.
2. **The audit exposed the dataset's own structure before any model
   existed**: 89.5% of fraud rows are later attempts, every card has
   exactly ONE fraud burst of at most 2.0 days, so a 30-day-maturity
   blocklist recovers 0.0% while a 1-day one recovers 49.8% at 0.3%
   precision (cards live on legitimately for years after their burst).
   All confirmed by hand against the raw data. An honest instrument.
3. **Bring-your-own-scorer, end to end**: trained my own transaction-only
   LightGBM chronologically (train < day 855, isotonic calibration on days
   855-975, audit the last 120 days), wrote one parquet with `my_score`
   and `my_p`, re-ran. Result, on my numbers (`audit_sparkov.txt`):
   headline AP 0.153 / AUC 0.576; **at the primary 5 alerts/day budget:
   36% headline recall vs 19% of fraud cases stopped at the first attempt,
   94% redundancy, 426 wrongly flagged** - the distortion the tool exists
   to measure, measured on data and a model its authors never saw.
4. **The tool argues against its own flagship feature when the data says
   so**: `route` at 30-day maturity flags 4,856 transactions on 27 known
   cards, ALL of them labelled legitimate, and lifts first-strike recall
   1.00x - because Sparkov fraud never recurs per card. The output counts
   the harm itself ("the standing policy's own cost, counted"). On this
   book the correct decision is do-not-deploy-the-lane, and the tool is
   what tells you that. (`route_sparkov_30d.txt`, `_1d.txt`.)
5. **Policy**: 38.2% savings vs approve-all at central economics, beats
   the best fixed threshold, and volunteers its own losing corner
   (-0.23% at m=0.05). (`policy_sparkov.txt`.)
6. **TUI on foreign data**: `strikeone tui --source eval_scored.parquet`
   (mapping picked up from `.strikeone.toml`) renders AUDIT / ROUTE /
   CASE with the same big-number treatment as the worked example
   (`tui_audit_sparkov.png`, `tui_route_sparkov.png`,
   `tui_case_sparkov.png`).
7. **No-overclaim check**: nothing in any output suggested the authors'
   IEEE-CIS model applies to this data; the worked example is labelled a
   worked example everywhere it appears.

## Findings filed (all fixed in the follow-up commit, retested)

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | low | mapping a string column as `label` misdiagnosed as "1,323,347 rows have a missing label" | detects non-numeric labels and says so, with the derive-first hint |
| F2 | medium | the GAP sentence attributed role-based redundancy to "a {delay}-day blocklist", misleading when that blocklist's recovery is 0% (as here) | sentence now says "later attempts by fraudsters already detected in this window" |
| F3 | **high** | the TUI ROUTE screen said "The routing protects any scorer" unconditionally - false on this dataset (lift 1.00x, 4,856 legit blocks) | sentence is now conditional on measured lift; at <=1.05x it reads "MEASURED: the blocklist lane adds nothing on this book ... do not deploy the lane" |
| F4 | medium | TUI had no `--source`, so it could not be pointed at a custom file headlessly | `--source` flag added, mapping resolved as in F5 |
| F5 | medium | TUI path-loading ignored the persisted `.strikeone.toml` that the CONNECT screen promises to use | rpc `init` now loads the mapping beside the source file or in the cwd, with a clear error otherwise |
| F6 | **high** | `--frame` captures exited 400ms after `ready`, before slow RPC results landed on larger data - AUDIT/ROUTE frames rendered "no dataset loaded" on this 166k-row file (worked on IEEE-CIS only by luck of timing) | frame mode now waits for the specific tab's content |

Two additional notes, not defects: numeric timestamps are documented as
epoch seconds (PaySim-style hour-steps need a one-line preprocess), and
the `policy` full grid is slow on ~1M-row frames (the TUI already uses
the fast no-grid path; CLI users can wait or pre-slice).

## Verdict

The product does what the README sells to a stranger: one mapping, no
code, and it produced the corrected evaluation of MY model on MY data,
including the two results a vendor tool would be tempted to hide - that
its own routing lane should not be deployed on this book, and exactly
where its cost policy loses to a plain threshold. Two high-severity
findings (an overclaiming sentence and a broken capture path) were found
and fixed during the test. Repo invariants held throughout: the IEEE-CIS
holdout access log still has exactly one entry, and no frozen artifact
was touched.
