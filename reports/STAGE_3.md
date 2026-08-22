# Stage 3 — The episode engine

## Surprises first

1. **The fragmentation prerequisite caught a fatal-class bug before it
   could do damage.** pandas 3's `astype(str)` propagates NA instead of
   writing `"nan"`, so `build_uid` silently produced null UIDs for the
   11.4% fallback rows, and `episode_roles` counted each null-UID fraud as
   its own singleton "first strike". Fixed, regression-tested (null UIDs
   now raise), every affected number rebuilt; STAGE_2.md carries a
   correction banner. The corrected first-strike counts are materially
   different (e.g., 1,040 val FS episodes, not the contaminated 1,610).
2. **B is genuinely worse at first strikes, not just "no better":**
   paired ΔFS-recall = **−0.0163 [−0.0307, −0.0027]**, p(no improvement)
   = 0.988 — the CI excludes zero at the primary budget.
3. **At tight budgets the distortion is catastrophic, not marginal:** at
   budget 500, B's first-strike recall is **7.9% vs A's 21.0%** (friction
   efficiency 0.16 vs 0.44). B's top scores are saturated with
   already-flagged entities. Tight budgets are exactly where production
   review queues operate.
4. **The behavioural-harm mechanism I hypothesised in Stage 2 was wrong,
   and the segmentation proves the true one:** the −0.017 AP harm
   concentrates entirely in the *known-entity* segment (−0.0657
   [−0.0798, −0.0520]) and is nil on novel entities (+0.0005). Windowed
   history features actively mislead where they are populated; they are
   not dilution. STAGE_2.md corrected.
5. **First strikes are a novel-entity phenomenon: 1,027 of 1,040 val
   first-strike episodes (98.8%) are on entities unseen before day 120.**
   The known-entity segment has 13 first strikes against 878 propagated
   positives (99.2% redundancy for every model there).

## Prerequisite: fragmentation ruled out

Materiality thresholds were stated before computing (script header).
Results:

- **D1 is integral**, so `floor(day − D1) = day_idx − D1` exactly.
- **The card1-vs-UID novelty gap is not a tension**: card1 is a card
  *attribute* (cardinality 13,553 over 590k rows) — a bucket that recurs —
  while UID approximates a client. Attribution of val UID novelty: 91.8%
  changed first-seen-day on a known (card1, addr1) pair — a new client on
  a recycled bucket — 6.0% novel addr1, 2.2% novel card1.
- Distinct first-seen values per multi-transaction (card1, addr1) pair:
  24% one value, 25% two, 51% three-plus — but pairs legitimately host
  multiple clients, and the median gap between adjacent first-seen values
  is **9 days** (boundary jitter would produce gaps of 1; only 23% of
  multi-value pairs have any gap of 1, an upper bound that mostly reflects
  clients starting a day apart).
- **M3, the decisive check: 12 of 1,040 val first-strike episodes (1.15%)
  have a ±1-first-seen sibling with earlier fraud** — the only pattern
  that would convert a first strike into a propagated row under a merged
  entity. Below the 5% materiality bar. **Not material; the metric
  definition stands.**
- Fallback (null-addr1) pseudo-UIDs are larger (mean 3.61 vs 2.53 txns)
  but their fraud episodes are *not* (2.36 vs 2.63 fraud txns/episode):
  pooling does not manufacture propagated labels at scale.
- Partition coverage: 100% of rows belong to exactly one entity; 88.8% at
  client resolution, 11.1% pooled at card1×first-seen (addr1 null), 0.2%
  coarser (D1 null). All rows participate in every episode metric at
  their stated resolution; the key-sensitivity analysis bounds the effect
  of the pooling choice.

## A. The episode table

Primary budget 2,810 alerts (= val positives; ~100/day). **Blocklist** is
the named reference everywhere from now on: score := 1[transaction's UID
has a known fraud ≥ 7 days old], nothing else, evaluated at its natural
operating point (1,711 alerts). By construction it catches zero first
strikes — which is the point.

| Model | alerts | FS catch | redundant | FP | FS precision¹ | FS recall | loss-wt FS recall | prop. recall | redundancy rate | txn precision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Blocklist** | 1,711 | **0** | 928 | 783 | 0.000 | 0.000 | 0.000 | 0.524 | 1.000 | **0.542** |
| A | 2,810 | 591 | 939 | 1,280 | 0.210 | **0.568** | 0.415 | 0.531 | 0.614 | 0.544 |
| A+beh | 2,810 | 600 | 903 | 1,307 | 0.214 | 0.577 | 0.445 | 0.510 | 0.601 | 0.535 |
| A+fam | 2,810 | 588 | 945 | 1,277 | 0.209 | 0.565 | 0.419 | 0.534 | 0.616 | 0.546 |
| B | 2,810 | 574 | 1,346 | 890 | 0.204 | 0.552 | 0.405 | **0.761** | **0.701** | **0.683** |

¹ FS precision = FS catches / total alerts = friction efficiency (same
quantity, named once).

**The quotable pair (budget-matched at the blocklist's own N=1,711): a
UID blocklist with no model achieves 54.2% transaction precision — enough
to look respectable on any precision dashboard — while catching zero
first strikes by construction. Baseline A at the same 1,711 budget
reaches 73.1% precision and catches 525 first strikes.** (An earlier
draft compared A at budget 2,810 — 54.4% — against the blocklist at
1,711; that comparison was not budget-matched and is retired.) Meanwhile
B at 1,711 posts 90.5% precision with *lower* first-strike recall than A
(0.397 vs 0.505): precision rises as prevention falls. And at 2,810, B —
the model that "wins" the headline (AP 0.748 vs 0.573) — redirects 407
alerts from fresh fraud and legitimate customers toward entities a
blocklist already covers (redundant 939 → 1,346).

First-strike recall with uid-cluster bootstrap CIs, and paired deltas
vs A (primary budget):

| Model | FS recall [95% CI] | Δ vs A [95% CI] | p(no improvement) |
|---|---|---|---|
| Blocklist | 0.000 | −0.568 [−0.597, −0.538] | 1.000 |
| A | 0.568 [0.538, 0.597] | — | — |
| A+beh | 0.577 [0.547, 0.604] | +0.009 [−0.005, +0.022] | 0.124 |
| A+fam | 0.565 [0.535, 0.595] | −0.003 [−0.016, +0.009] | 0.698 |
| B | 0.552 [0.521, 0.579] | **−0.016 [−0.031, −0.003]** | 0.988 |

- **B's first-strike drop is confirmed, CI excluding zero.** The honest
  claim is "worse", not "no better".
- Loss-weighted FS recall (0.415 for A) sits well below unweighted
  (0.568): **the first strikes being missed skew large-amount** — a
  direct design input for Stage 4's cost weighting.

### Across the budget curve (`episode_table.csv`, `fig_kcurve.png`)

| Budget | FS recall A / B | Friction eff A / B |
|---|---|---|
| 500 | **0.210 / 0.079** | **0.436 / 0.164** |
| 1000 | 0.386 / 0.174 | 0.402 / 0.181 |
| 2000 | 0.526 / 0.467 | 0.274 / 0.243 |
| 2810 | 0.568 / 0.552 | 0.210 / 0.204 |
| 8000 | 0.710 / 0.726 | 0.092 / 0.094 |

The headline-vs-episode inversion grows as budgets tighten: B needs ~4,000
alerts to do what A does with fewer, because its ranking spends the top of
the queue re-flagging known entities. Only at very loose budgets (8,000 ≈
2.8× the positive count) does B pull level.

## B. Does the UID family buy first-strike recall? No.

ΔFS-recall(A+fam − A) = −0.003 [−0.016, +0.009], p = 0.698. The family's
transaction-level effect (+0.0048 AP, lower CI bound exactly 0.0000) is
**not distinguishable from zero**, and it buys **zero first-strike
value**. Once the propagation
artifact is stripped out, relational entity history contributes nothing to
catching new fraud on this dataset — the cleanest available answer to
whether "relational intelligence" was ever about prevention here.

## C. Novelty segmentation (design input for Stage 4)

Entities split by "UID seen before day 120" (all prior data):

| Segment | rows | positives | FS episodes | A: FS recall / redundancy | B: FS recall / redundancy | Blocklist prop. recall |
|---|---:|---:|---:|---|---|---|
| known | 37,803 | 891 | **13** | 0.231 / 0.992 | 0.231 / 0.996 | **0.928** |
| novel | 42,151 | 1,919 | **1,027** | 0.573 / 0.492 | 0.556 / 0.493 | 0.127 |

- **The known-entity segment is a blocklist's world**: 13 first strikes
  vs 878 propagated positives; a blocklist alone recovers 92.8% of its
  positives; every model's interventions there are ≥99% redundant.
- **The 98.8% figure, with its denominator and definitional coupling
  stated**: a known entity can only produce a val first strike if it was
  clean through day 119 — and 158,106 of 163,892 known UIDs were. Of the
  18,483 clean known UIDs active in validation, **13 struck (onset rate
  0.07%)**; of 24,325 novel UIDs, **1,027 struck (4.22%)** — a **60×
  onset-rate difference** that survives the coupling.
- **The fallback (null-addr1) stratum is a segment of its own**: fraud
  rate **12.9% in val vs 2.45%** for resolved entities (10.9% vs 2.5% in
  train), and it hosts 487 of 1,026 attributable first strikes on 10.2%
  of rows. A missing billing address is itself a strong signal, and a
  segment with a 5× base rate plausibly wants its own policy (Stage 4
  input).
- **The novel-entity segment is where prevention happens**: 98.8% of
  first strikes, no history, transaction features only.
- Policy implication for Stage 4: score-driven intervention earns its
  friction almost exclusively on novel entities; on known-flagged
  entities the correct instrument is the blocklist, at zero model
  friction.
- Mechanism check (surprise 4): A+beh's AP harm is −0.0657 in the known
  segment, +0.0005 in the novel — windowed behavioural features mislead
  precisely where they are populated.

## D. Entity-key sensitivity

Same scores, roles recomputed under three keys:

| Key | FS episodes | A: FS recall / friction eff / redundancy | B: same |
|---|---:|---|---|
| uid (primary) | 1,040 | 0.568 / 0.210 / 0.614 | 0.552 / 0.204 / 0.701 |
| card1 | 155 | 0.516 / 0.029 / 0.948 | 0.497 / 0.027 / 0.960 |
| card1+email | 335 | 0.445 / 0.053 / 0.903 | 0.472 / 0.056 / 0.918 |

- **The core claim is key-robust**: under every key, B's propagated
  recall soars (+15–23pp, not shown) while first-strike recall barely
  moves, and B's redundancy rate exceeds A's.
- **One secondary claim is key-dependent and reported as such**: "B is
  significantly *worse* at first strikes" holds under uid (CI excludes
  zero) and directionally under card1, but the sign flips under
  card1+email: +0.0269 [−0.0062, +0.0604], p(no improvement) = 0.073 —
  a CI straddling zero (cluster bootstrap by that key's entities;
  computed at the Stage 4 gate's request). The defensible form across all
  keys is: **"B is no better at first strikes under any key, and
  significantly worse under the primary key."**
- Coarser keys collapse friction efficiency (0.21 → 0.03) by inflating
  propagated counts — the choice of propagation key moves magnitudes a
  lot, which is why every episode number in this project names its key.

## E. False positives, hand-inspected: precision is a lower bound

The host acknowledges unreported fraud is labelled legitimate. Among B's
15 top-scored "false positives" (`fp_inspection_topB.csv`):

- **TransactionID 3398072 / 3398085 — same entity, uid `3154_nan_92`,
  which has 3 labelled frauds.** These two legit-labelled rows are
  same-day, same-amount (12.446), same C-profile as the entity's own
  labelled frauds. If the labels are right, this customer coincidentally
  transacts identically to their own fraud episode.
- **A same-day spray on day 120**: four distinct card1 buckets, identical
  odd amount 12.446 (plus two at 8.58), all ProductCD=C, all hotmail.com,
  no device info, C1≈22 — and the card buckets involved carry 158–231
  labelled frauds each. This is one campaign's fingerprint, labelled
  legitimate.
- **TransactionID 3460709 / 3460732**: two "different" entities, same
  day, same device build (Moto G NPJ25.93-14.7), same amount 176.448; one
  of the two uids has 2 labelled frauds.
- Counter-example, honestly: 3454325 is scored 0.97 by B but 0.22 by A —
  a pure blocklist echo (uid has 3 old frauds; nothing about the
  transaction itself is remarkable). B's FP list mixes plausible
  unreported fraud with propagation echoes; A's list (also committed) is
  cleaner evidence for the lower-bound claim.

## Gate checklist

- [x] Fragmentation ruled out with pre-stated thresholds (M3 = 1.15% < 5%)
- [x] Reporting fixes: ablation convention stated (add-one-to-A ≡
      leave-one-out here, residual = interaction); p-column relabelled
      "p(no improvement)" with footnote; behavioural-harm mechanism
      corrected to the measured one
- [x] Episode table for Blocklist/A/A+beh/A+fam/B across 8 budgets with
      uid-cluster paired CIs at the primary budget
- [x] UID-family first-strike test (null)
- [x] Novelty segmentation + mechanism check
- [x] Key sensitivity (core claim robust; the one key-dependent claim
      flagged)
- [x] FP inspection committed (both A-top and B-top lists)
- [x] Holdout access log verified empty at the end of every script
