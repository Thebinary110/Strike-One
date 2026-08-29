# Prior art — who said what first, and what is actually left

Strike One's central move — credit a fraud model only for the first
labelled transaction of a case, because everything after it a lookup
table would also have caught — is not new. This page lists where each
piece already exists, so the README can claim only the remainder.

## The first-transaction framing existed before us

**Nguyen et al., AISTATS 2022 (arXiv:2204.05265)** evaluate card fraud
models per compromised card rather than per transaction, and state the
framing in one sentence, verbatim:

> "instead of considering the transaction with the highest score, we
> consider the score predicted for the first fraudulent transaction on
> the card."

That is the first-hit idea, in print, before this project. Our episode
metric is the same idea applied at a matched review budget with the
blocklist counterfactual made explicit.

**The Fraud Detection Handbook** (Le Borgne, Siblini, Lebichot,
Bontempi, ULB 2022) ships **Card Precision@k** with
`remove_detected_compromised_cards=True` as the *default*: once a card
is known compromised, its later transactions are dropped from the
evaluation. Deduplicating already-caught entities from the metric is
therefore standard practice in the closest open reference
implementation, not our invention.

**Dal Pozzolo, Boracchi, Caelen, Alippi, Bontempi (IEEE TNNLS 2017)**
formalised the two label mechanisms this project leans on: verification
latency (labels arrive days later — our `--delay`) and the
alert–feedback interaction (today's alerts shape tomorrow's labels).
The 7-day delayed-label machinery here is an implementation of their
problem statement.

**Hand, Whitrow, Adams, Juszczak, Weston (JORS 2008)** argued for
account-level, time-aware performance criteria for plastic-card fraud
tools and against transaction-level ROC-style summaries — the
grandfather of "count cases, not rows".

## The metric-inversion literature — noting we run it BACKWARDS

**Tatbul, Lee, Zdonik, Alam, Gottschlich (NeurIPS 2018)** (range-based
precision/recall) and **Kim, Choi, Choi, Lee, Yoon (AAAI 2022)** (the
point-adjust critique) both study how event-level credit changes
time-series anomaly rankings. Their direction is *generous*: catching
any point of an anomalous segment earns credit for the segment, and Kim
et al. show that generosity lets trivial detectors win. Our direction is
the **inversion** of that: catching a later point of a fraud episode
earns *nothing*, because a blocklist already covers it. Same family of
metric surgery, opposite sign — cited so nobody mistakes one for the
other.

## Cost-sensitive decisions — solved long ago

**Elkan (IJCAI 2001)** gives the foundations of cost-sensitive
decision-making from calibrated probabilities; **Bahnsen, Aouada,
Ottersten (2014–2016)** apply example-dependent costs (amount-dependent,
exactly our table) to card fraud; **Yildirim et al. (AIAI 2018, PONRM)**
build a profit-oriented three-way decision model for transactions. Our
`policy` command — expected-cost argmin over approve / step-up / block
with declared parameter ranges — is a careful implementation of that
literature. **It is correct engineering, not a contribution**, and this
repo does not claim it as one.

Industry practice covers the rest of the decision layer: **Stripe
Radar** publishes score-plus-rules routing with review budgets, and
**Adyen's Dynamic 3DS** chooses step-up per transaction on economic
grounds, including liability shift — the `s` parameter in our cost model
models the mechanism their product already prices.

## Adjacent recent work

**Malik (arXiv:2604.23494)** and **Khadka & Das (arXiv:2605.02979)**
were flagged in review as adjacent recent treatments of label quality
and evaluation practice in payment fraud; they are cited so a reader can
compare framings directly rather than take our narration for it.

## What is actually left to claim (narrow, and all of it measured)

1. **The selection-distortion measurement.** Not that labels propagate
   (known), but *how much the propagated share bends model selection*:
   on IEEE-CIS, the label-derived-feature model B beats baseline A by
   +0.17 AP on the standard metric while catching *fewer* cases at their
   first labelled transaction at tight budgets — the metric picks the
   worse-at-first-hits model, and the effect shrinks on the holdout
   exactly as the propagated share does. Demonstrated under a sealed
   holdout, opened against a pre-registered prediction of that shrinkage.
2. **The audit as a shippable, bring-your-own-scorer tool.** Budget-
   matched blocklist counterfactual, blocklist-coverable share, window-
   truncation and label-maturity caveats printed *with* the numbers, and
   refusal behaviours (uncalibrated input, non-propagating labels) — the
   evaluation practice from the literature packaged so a fraud team can
   run it on an export in one command.
3. **The friction accounting.** "X of your correct alerts were
   blocklist-coverable" as an operational, per-budget report rather than
   a metric footnote.

Nothing else. The episode idea is Nguyen et al.'s and the handbook's;
the label mechanics are Dal Pozzolo et al.'s; the case-level stance is
Hand et al.'s; the cost engine is Elkan/Bahnsen/Yildirim; the routing
economics are shipping today at Stripe and Adyen.
