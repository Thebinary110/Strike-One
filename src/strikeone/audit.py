"""`strikeone audit` — the product's face.

Point it at labelled transactions and it prints, in this order: what it
read (honestly, before any result), the number you already have (AP,
ROC-AUC), the number nobody has (fraud cases stopped on the very first
attempt, at your review capacity), the gap in one plain sentence, what a
blocklist gets you for free, one concrete next action, and a footer of
what was assumed and NOT measured.

The default output is written for a payments ops lead, fits a standard
terminal, and must stand on its own pasted into Slack with colour
stripped. Technical detail lives in --verbose and --json. Colour is
green = prevented, amber = wasted, red = harm, nothing else, and only on
a TTY without NO_COLOR.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from strikeone import entity as ent_mod
from strikeone import episodes
from strikeone import metrics as M

BUDGET_MENU = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
W = 74  # output width: fits a default terminal and a Slack code block


def _c(code):
    return lambda s: f"\x1b[{code}m{s}\x1b[0m"


_GREEN, _AMBER, _RED, _BOLD = _c("32;1"), _c("33;1"), _c("31;1"), _c("1")
_PLAIN = lambda s: s  # noqa: E731


@dataclass
class AuditResult:
    stats: dict
    blocklist: dict
    budgets: list = field(default_factory=list)
    headline: dict | None = None
    sentence: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {"stats": self.stats, "blocklist": self.blocklist,
             "headline": self.headline, "budgets": self.budgets,
             "sentence": self.sentence},
            indent=2, default=float,
        )

    # ---------------------------------------------------------- rendering
    def to_text(self, color: bool = False, verbose: bool = False) -> str:
        g, a, r, b = (_GREEN, _AMBER, _RED, _BOLD) if color else (_PLAIN,) * 4
        s, bl = self.stats, self.blocklist
        rule = "─" * W
        L: list[str] = []
        L.append(b("STRIKE ONE") + "  fraud-operation audit")
        L.append(rule)

        # a) what was read, honestly, before any result
        L.append(b("WHAT WAS READ"))
        L.append(f"  {s['rows']:,} transactions over {s['span_text']}")
        L.append(f"  {s['positives']:,} labelled fraud "
                 f"({s['positive_rate']:.2%}); no rows were dropped")
        res_pct = s["entity_resolution"]
        if res_pct < 0.95:
            L.append(f"  the entity key resolves cleanly on {res_pct:.1%} of "
                     "rows; the rest pool into")
            L.append("  coarser identities, so every case count below leans "
                     "conservative")
        else:
            L.append(f"  entity key resolves cleanly on {res_pct:.1%} of rows")
        L.append(f"  fraud labels assumed knowable "
                 f"{s['label_delay_days']:g} days after the transaction")
        L.append("")

        if self.headline:
            h = self.headline
            pr = next(x for x in self.budgets if x["primary"])
            # b) the number they already have
            L.append(b("THE NUMBER YOU ALREADY HAVE"))
            L.append(f"  average precision {h['ap']:.4f}, "
                     f"ROC-AUC {h['roc_auc']:.4f}")
            if s.get("capacity_stated"):
                L.append(f"  at your stated {pr['per_day']:,} reviews/day:")
            else:
                L.append(f"  at {pr['per_day']:,} reviews/day, inferred from "
                         "your fraud volume")
                L.append("  (pass --capacity to use your real number):")
            L.append(f"  {pr['headline_recall']:.0%} of fraud transactions "
                     "caught, "
                     + r(f"{pr['false_positives']:,} good customers flagged"))
            L.append("")

            # c) the number nobody has
            L.append(b("THE NUMBER NOBODY HAS"))
            L.append("  " + g(f"{pr['fs_recall']:.1%} of fraud CASES stopped "
                              "on the very first attempt"))
            L.append(f"  at those same {pr['per_day']:,} reviews/day. That is "
                     "the only moment a loss")
            L.append("  is prevented; everything after it, a blocklist "
                     "catches for free.")
            L.append("")

            # d) the gap, one plain sentence, their numbers
            L.append(b("THE GAP, IN YOUR NUMBERS"))
            for line in _wrap(self.sentence, W - 2):
                L.append("  " + line)
            L.append("")

            # e) redundancy + blocklist-recoverable share
            L.append(b("WHAT A BLOCKLIST GETS YOU FOR FREE"))
            L.append("  a plain blocklist, no model, recovers "
                     + a(f"{bl['recovered_share']:.1%}")
                     + " of your labelled fraud")
            comp = bl["precision_vs_scorer"]
            L.append(f"  at {bl['precision']:.1%} precision, while stopping "
                     + r("0") + " cases on the first attempt.")
            if comp is not None:
                L.append("  That precision is "
                         + (f"{comp:.0%} of" if comp < 1 else "MORE than")
                         + " your scorer's at the same capacity.")
            L.append("")

            # f) estimated routing lift + one concrete action
            L.append(b("ONE THING TO DO NEXT"))
            freed = pr["alerts_on_flagged_per_day"]
            if freed >= 0.5:
                L.append("  routing already-flagged entities to a blocklist "
                         "lane would free about")
                L.append("  " + a(f"{freed:.0f} of your {pr['per_day']:,} "
                                  "reviews/day")
                         + " for fraud that is actually new.")
            else:
                L.append("  at your label maturity, almost none of your "
                         "reviews land on entities a")
                L.append("  blocklist could already know; a routing lane "
                         "would change little here.")
            L.append("  Measure it on your scorer: strikeone route "
                     "<your file>")
            L.append("")

            # the working table, compact
            L.append(b("AT OTHER REVIEW BUDGETS"))
            L.append(f"  {'reviews/day':>11} {'txns caught':>11} "
                     f"{'stopped 1st':>11} {'wasted-on-known':>15} "
                     f"{'good flagged':>12}")
            for row in self.budgets:
                mark = " <-capacity" if row["primary"] else ""
                L.append(f"  {row['per_day']:>11,} "
                         f"{row['headline_recall']:>11.1%} "
                         f"{row['fs_recall']:>11.1%} "
                         f"{row['redundancy_rate']:>15.1%} "
                         f"{row['false_positives']:>12,}{mark}")
            L.append("")
        else:
            L.append(b("NO SCORE COLUMN"))
            for line in _wrap(self.sentence, W - 2):
                L.append("  " + line)
            L.append("")
            L.append(b("WHAT A BLOCKLIST GETS YOU FOR FREE"))
            L.append("  a plain blocklist, no model, recovers "
                     + a(f"{bl['recovered_share']:.1%}")
                     + " of your labelled fraud at")
            L.append(f"  {bl['precision']:.1%} precision, stopping "
                     + r("0") + " cases on the first attempt")
            L.append("")

        if verbose:
            L.append(b("TECHNICAL (also in --json)"))
            L.append(f"  fraud cases (episodes): {s['episodes']:,}; later "
                     f"attempts by known fraudsters: {s['propagated_rows']:,} "
                     f"({s['propagated_share_of_positives']:.1%} of fraud "
                     "rows)")
            L.append(f"  entities: {s['entities']:,}; blocklist-flagged rows "
                     f"under the delay: {bl['flagged_rows']:,}")
            if self.budgets:
                effs = ", ".join(
                    f"{x['per_day']}/d={x['friction_efficiency']:.1%}"
                    for x in self.budgets[:6])
                L.append("  friction efficiency (first-attempt catches per "
                         f"review): {effs}")
            L.append("")

        # g) assumed, not measured
        L.append(rule)
        L.append(b("ASSUMED, NOT MEASURED"))
        L.append(f"  fraud labels mature in {s['label_delay_days']:g} days "
                 "here; slower maturity shrinks")
        L.append("  every blocklist figure above. Case boundaries come from "
                 "your entity key;")
        L.append("  a coarser or finer key moves them. This audit evaluates "
                 "only the score")
        L.append("  column you provided: no other model was applied to your "
                 "traffic, and")
        L.append("  nothing about your data left this machine.")
        return "\n".join(L)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        if len(cur) + len(w_) + 1 > width:
            lines.append(cur)
            cur = w_
        else:
            cur = f"{cur} {w_}".strip()
    if cur:
        lines.append(cur)
    return lines


def _budget_grid(n_rows: int, days: float, positives: int,
                 capacity: float | None = None) -> tuple[list, int]:
    grid = [x for x in BUDGET_MENU if x * days <= 0.25 * n_rows]
    if not grid:
        grid = [max(1, int(0.01 * n_rows / max(days, 1)))]
    if capacity:
        cap = int(capacity)
        if cap not in grid:
            grid = sorted(set(grid + [cap]))
        return grid, cap
    per_day_pos = positives / max(days, 1)
    return grid, min(grid, key=lambda x: abs(x - per_day_pos))


def audit(df: pd.DataFrame, label_delay_days: float = 7.0,
          capacity_per_day: float | None = None) -> AuditResult:
    df = df.sort_values(["t", "transaction_id"]).reset_index(drop=True)
    t = df["t"].to_numpy()
    tb = df["transaction_id"].to_numpy()
    y = df["label"].to_numpy().astype(int)
    amt = df["amount"].to_numpy(dtype=float)
    ent = df["entity"].to_numpy()
    days = float((t.max() - t.min()) / 86400.0)
    n, pos = len(df), int(y.sum())

    roles = episodes.episode_roles(ent, t, y, tiebreak=tb)
    fs = roles == episodes.ROLE_FIRST_STRIKE
    prop = roles == episodes.ROLE_PROPAGATED
    n_eps = int(fs.sum())

    bl_stats = ent_mod.pit_delayed_label_stats(
        pd.Series(ent), t.astype(np.int64), y, tb,
        delay_days=label_delay_days, prefix="e",
    )
    flag = np.nan_to_num(bl_stats["e_fraud_rate"].to_numpy()) > 0
    rec_rows = int((flag & (y == 1)).sum())
    rec_amt = float(amt[flag & (y == 1)].sum())
    pos_amt = float(amt[y == 1].sum())

    # real dates only when timestamps are plausibly epoch seconds
    if t.min() > 3e8:
        d0 = datetime.fromtimestamp(t.min(), tz=timezone.utc).date()
        d1 = datetime.fromtimestamp(t.max(), tz=timezone.utc).date()
        span_text = f"{days:.0f} days ({d0} to {d1})"
    else:
        span_text = f"{days:.1f} days (relative timestamps)"

    resolution = float(1 - pd.Series(ent).astype(str)
                       .str.contains("nan").mean())

    stats = {
        "rows": n, "days": days, "span_text": span_text,
        "positives": pos, "positive_rate": pos / n,
        "episodes": n_eps,
        "propagated_rows": int(prop.sum()),
        "propagated_share_of_positives":
            float(prop.sum() / pos) if pos else 0.0,
        "label_delay_days": label_delay_days,
        "entities": int(pd.Series(ent).nunique()),
        "entity_resolution": resolution,
        "rows_dropped": 0,
        "capacity_stated": capacity_per_day is not None,
    }
    blocklist = {
        "flagged_rows": int(flag.sum()),
        "recovered_rows": rec_rows,
        "recovered_share": rec_rows / pos if pos else 0.0,
        "recovered_amount_share": rec_amt / pos_amt if pos_amt else 0.0,
        "precision": float(y[flag].mean()) if flag.any() else 0.0,
        "precision_vs_scorer": None,
        "first_strike_catches": int((flag & fs).sum()),
    }

    res = AuditResult(stats=stats, blocklist=blocklist)

    if "score" in df.columns and df["score"].notna().any():
        s = df["score"].fillna(-np.inf).to_numpy(dtype=float)
        res.headline = {"ap": M.average_precision(y, s),
                        "roc_auc": M.roc_auc(y, s)}
        grid, primary = _budget_grid(n, days, pos, capacity_per_day)
        for per_day in grid:
            budget = int(per_day * days)
            alert = M.alerts_at_budget(s, budget)
            on_pos = int((alert & (y == 1)).sum())
            fs_c = int((alert & fs).sum())
            red = int((alert & prop).sum())
            res.budgets.append({
                "per_day": per_day, "budget": budget,
                "headline_recall": on_pos / pos if pos else 0.0,
                "false_positives": int(budget - on_pos),
                "fs_recall": fs_c / n_eps if n_eps else 0.0,
                "redundancy_rate": red / on_pos if on_pos else 0.0,
                "friction_efficiency": fs_c / budget if budget else 0.0,
                "precision": on_pos / budget if budget else 0.0,
                "alerts_on_flagged_per_day":
                    float((alert & flag).sum() / max(days, 1)),
                "primary": per_day == primary,
            })
        pr = next(x for x in res.budgets if x["primary"])
        if pr["precision"] > 0:
            blocklist["precision_vs_scorer"] = (
                blocklist["precision"] / pr["precision"])
        n_red = int(round(pr["redundancy_rate"]
                          * pr["headline_recall"] * pos))
        res.sentence = (
            f"{n_red:,} of the alerts your metric counts as wins were later "
            f"attempts by fraudsters already caught in this window. Those "
            f"prevented nothing. Counted by fraud cases stopped on the "
            f"first attempt, you stop {pr['fs_recall']:.0%}; your headline "
            f"number reads {pr['headline_recall']:.0%}."
        )
    else:
        res.sentence = (
            f"No score column was mapped, so this reads your label "
            f"structure only: {blocklist['recovered_share']:.0%} of your "
            f"labelled fraud sits on entities a {label_delay_days:g}-day "
            f"blocklist already knows, meaning a transaction-level metric "
            f"can be that share 'right' while preventing nothing. Re-run "
            f"with --map score=<your model column> to measure your own gap."
        )
    return res
