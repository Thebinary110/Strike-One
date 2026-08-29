# The five minutes — final script

~700 words spoken. Rehearse to 4:40. Every number below matches a row of
`reports/stage7/canonical_comparisons.md` (IDs in brackets, not spoken).
Holdout numbers only, except one sentence of validation for the
replication point [C3v]. Frames for beats 1–3 and 5 are in
`video/slides.html`; beats with live assets use the TUI and repo.

---

## 0:00–0:25 · Cold open — SLIDE 1

> On the most widely used public benchmark for card fraud, the standard
> evaluation cannot distinguish preventing fraud from remembering it —
> and it systematically prefers the model that remembers. I measured how
> much, and built the fix.

## 0:25–0:50 · The product — terminal, live

(Terminal: `pip install -e .`, then run the audit against a mapped file.)

> This ships as a package. pip install, point it at your own labelled
> transactions with a one-time column mapping, and it tells you the number
> nobody's dashboard shows: how much of your fraud metric is remembering
> instead of preventing. Your data never leaves the machine. We ship the
> method and the measurement; you bring the scorer. The IEEE-CIS run
> you're about to see is the worked example that proves the method, not a
> deployable model.

## 0:50–1:25 · The mechanism — SLIDE 2, then the entity timeline

(TUI CASE tab on the worked example, "next case" pressed, for the
timeline shot.)

> The labels weren't assigned per transaction. Once a card is charged
> back, every later transaction sharing its account, email, or billing
> address is labelled fraud too. So the positive class holds two
> different things: the transaction where an episode *starts* — catching
> that prevents loss — and everything after it, which any blocklist
> already covers. Standard average precision credits both equally.
>
> Which means the metric rewards catching transactions a lookup table
> would have caught for free.

## 1:10–2:00 · The evidence, holdout only — SLIDES 3, 4, 5

> Everything from here is a sealed out-of-time holdout, opened once.
>
> Lesson one [C1]: a blocklist alone — no model at all — reaches 49.8%
> transaction precision and prevents literally zero episodes. Precision
> tells you nothing about prevention.
>
> Lesson two [C1]: the model that wins every headline metric — 89.1%
> precision against 69.9% — stops 442 episodes at first strike against
> 566. Better by every standard measure, 22% worse at the only thing that
> stops loss.
>
> And that's a replication [C3, C3v]: significantly worse at first
> strikes on validation, and again on the holdout. The confidence
> interval excludes zero both times.

Optional 8s, only with the caveat in the same breath [C8]:

> That headline model scores above the winning Kaggle solution's
> private-leaderboard AUC. Different test set, so not like-for-like — but
> it gets there on features that encode the labelling rule, while
> preventing less. That's not a brag. It's the bug.

## 2:00–3:15 · The TUI, live — screen recording, one take

`strikeone tui`, IEEE-CIS worked example loaded. Drive: AUDIT tab at the
primary budget → `h` twice to tighten the budget → tab to ROUTE (both
curves on screen) → tab to CASE and let the case unfold. The
wrongly-flagged column stays on screen throughout.

> This is the terminal UI on the held-out month, through the frozen
> pipeline. The audit view: at a hundred alerts a day the headline metric
> says forty-seven percent recall; the corrected view says fifty-four
> percent of fraud cases stopped at the first attempt, with forty-eight
> percent of the correct alerts landing on entities a seven-day blocklist
> already knows, and one thousand six hundred seventy-six wrongly flagged
> good customers, on screen, in red.
>
> (h, h: budget to 20/day) Tighten the budget to what a small team
> actually has and the redundancy is still forty-five percent. The
> headline metric never shows you this column.
>
> (tab: ROUTE) And here's the part that works on their engine, not just
> mine: the same scorer, with and without the blocklist lane in front of
> it. At eighteen alerts a day the lane takes first-attempt recall from
> zero-point-one-zero to zero-point-two-three: two point three times the
> prevention, zero model changes [C4].
>
> (tab: CASE, the case unfolds) One fraud case, start to finish: quiet
> purchases, the first attempt in red, and everything after it already
> covered by the blocklist. Catching those later attempts is what the
> standard metric keeps rewarding.

## 3:15–4:00 · The honest ledger — SLIDE 6

> What I lose on [C7]: my system has the lowest precision of the three —
> 0.434, with 1,810 false positives at the default budget. That's a real
> cost, and a false positive is worse per unit than a redundant alert: it
> wastes an analyst *and* frictions a good customer. I'm not arguing my
> waste is better waste. Across the declared cost grid the trade prices
> out roughly break-even at unconstrained optima — my advantage is under
> capacity constraints, and I say so.
>
> Lane one also blocks 891 legitimate transactions [C7]. Counted and
> shown, not buried.
>
> I pre-registered nine predictions before opening the holdout. Six hit,
> three missed. All published — including the one where my own decay
> model was wrong in my favour.

## 4:00–4:40 · Why this is believable — SLIDE 7, then access log + ARCHITECTURE.md

> One sealed holdout. One entry in the access log — timestamped,
> hash-verified, in the repo. Predictions committed before the seal
> broke, including a called shot on the routing effect that landed inside
> its stated range [C4].
>
> Two fatal-class bugs caught by my own assertions — one of them a
> fifty-five percent inflation of my own favourite metric, found by an
> audit I ran on the thing I most wanted to be true.
>
> Chronological splits throughout. Point-in-time features. Paired
> confidence intervals on every comparison.

## 4:40–5:00 · The offer — SLIDE 8. Then cut.

> The yardstick is broken in a specific, measurable direction. Here's the
> corrected one — first-strike recall and friction efficiency. Here's the
> policy it selects: simpler, no entity aggregates, one blocklist set as
> its entire online state, under eight milliseconds p99.
>
> And here's the one line worth acting on regardless of what you run:
> route known-bad entities to a blocklist lane before they ever reach the
> model.

---

## Panel answers (memorise, don't read)

**"Your precision is the worst of the three — why deploy that?"**
Because precision is the metric under audit — a blocklist hits 49.8%
precision while preventing nothing [C1]. At fixed analyst capacity my
system stops more episodes [C5], and the FP cost is priced across the
declared grid, including the corner where my advantage vanishes
(m=0.25, a=0.20, e=0.95, c_h=60).

**"Isn't the blocklist lane just hard-coding the labelling rule?"**
Yes, deliberately. It's what a production system does anyway. Doing it
explicitly, at zero model cost, is what lets the model be evaluated on
what it uniquely contributes rather than on what a lookup table already
covers. And zero first strikes land in that lane — nothing preventable is
routed away from the model.

**"This is one public benchmark. Why should it apply to us?"**
It may not, and I didn't measure your data. But label propagation isn't a
quirk of this dataset's annotation — it's what any chargeback-derived
label set looks like, because real blocklists work the same way. The
method is a few hundred lines and it's in the repo. Run it on your own
labels and find out.

## Recording checklist

- [ ] TUI pre-loaded on the worked example; tab and budget key moves
      rehearsed to muscle memory; one unbroken ~75s take
- [ ] Every slide frame carries its source path in the corner (baked into
      `video/slides.html`)
- [ ] Rehearse ×5, time every take, target 4:40
- [ ] One take per beat, stitched; audio close and quiet
- [ ] Watch once at 2× before submitting
