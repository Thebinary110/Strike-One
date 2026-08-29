"""`strikeone audit` — the corrected evaluation, on anyone's labelled data.

Given transactions + binary labels + an entity key (+ optionally their own
model's scores), report:

  1. episode structure: fraud cases (episodes), first strikes vs later
     attempts on already-known entities
  2. how much of the labelled fraud a plain blocklist recovers by itself,
     given the stated label-availability delay
  3. if scores are present: headline AP / ROC-AUC, and at each review
     budget the headline-style recall vs FIRST-STRIKE recall, the
     redundancy rate, and friction efficiency
  4. the distortion, stated in their own numbers, in one plain sentence

Everything is computed point-in-time on the chronologically sorted frame
the contract layer produces. No data leaves the machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strikeone import entity as ent_mod
from strikeone import episodes
from strikeone import metrics as M

BUDGET_MENU = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]


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

    def to_text(self) -> str:
        s, b = self.stats, self.blocklist
        L = []
        L.append("STRIKE ONE AUDIT")
        L.append(f"  {s['rows']:,} transactions over {s['days']:.1f} days; "
                 f"{s['positives']:,} fraud-labelled ({s['positive_rate']:.2%})")
        L.append(f"  fraud cases (episodes): {s['episodes']:,}   "
                 f"first strikes: {s['episodes']:,}   "
                 f"later attempts on known entities: {s['propagated_rows']:,} "
                 f"({s['propagated_share_of_positives']:.1%} of fraud rows)")
        L.append("")
        L.append("BLOCKLIST RECOVERY (no model at all, "
                 f"{s['label_delay_days']:g}-day label delay)")
        L.append(f"  a plain blocklist recovers {b['recovered_rows']:,} of your "
                 f"fraud rows = {b['recovered_share']:.1%} of labelled fraud, "
                 f"{b['recovered_amount_share']:.1%} of fraud amount")
        L.append(f"  it stops 0 fraud cases at the first attempt, "
                 f"at {b['precision']:.1%} transaction precision")
        if self.headline:
            h = self.headline
            L.append("")
            L.append("YOUR SCORER, HEADLINE VIEW")
            L.append(f"  average precision {h['ap']:.4f}   "
                     f"ROC-AUC {h['roc_auc']:.4f}")
            L.append("")
            L.append("YOUR SCORER, CORRECTED VIEW (per review budget)")
            L.append("  alerts/day  headline recall  first-strike recall  "
                      "redundancy  friction eff.")
            for r in self.budgets:
                mark = "  <- primary" if r["primary"] else ""
                L.append(f"  {r['per_day']:>9,}  {r['headline_recall']:>14.1%}"
                         f"  {r['fs_recall']:>18.1%}  {r['redundancy_rate']:>9.1%}"
                         f"  {r['friction_efficiency']:>12.1%}{mark}")
        L.append("")
        L.append(self.sentence)
        return "\n".join(L)


def _budget_grid(n_rows: int, days: float, positives: int) -> tuple[list, int]:
    grid = [b for b in BUDGET_MENU if b * days <= 0.25 * n_rows]
    if not grid:
        grid = [max(1, int(0.01 * n_rows / max(days, 1)))]
    per_day_pos = positives / max(days, 1)
    primary = min(grid, key=lambda b: abs(b - per_day_pos))
    return grid, primary


def audit(df: pd.DataFrame, label_delay_days: float = 7.0) -> AuditResult:
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

    bl = ent_mod.pit_delayed_label_stats(
        pd.Series(ent), t.astype(np.int64), y, tb,
        delay_days=label_delay_days, prefix="e",
    )
    flag = np.nan_to_num(bl["e_fraud_rate"].to_numpy()) > 0
    rec_rows = int((flag & (y == 1)).sum())
    rec_amt = float(amt[flag & (y == 1)].sum())
    pos_amt = float(amt[y == 1].sum())

    stats = {
        "rows": n, "days": days, "positives": pos,
        "positive_rate": pos / n,
        "episodes": n_eps,
        "propagated_rows": int(prop.sum()),
        "propagated_share_of_positives": float(prop.sum() / pos) if pos else 0.0,
        "label_delay_days": label_delay_days,
        "entities": int(pd.Series(ent).nunique()),
    }
    blocklist = {
        "flagged_rows": int(flag.sum()),
        "recovered_rows": rec_rows,
        "recovered_share": rec_rows / pos if pos else 0.0,
        "recovered_amount_share": rec_amt / pos_amt if pos_amt else 0.0,
        "precision": float(y[flag].mean()) if flag.any() else 0.0,
        "first_strike_catches": int((flag & fs).sum()),
    }

    res = AuditResult(stats=stats, blocklist=blocklist)

    if "score" in df.columns and df["score"].notna().any():
        s = df["score"].fillna(-np.inf).to_numpy(dtype=float)
        res.headline = {"ap": M.average_precision(y, s),
                        "roc_auc": M.roc_auc(y, s)}
        grid, primary = _budget_grid(n, days, pos)
        for per_day in grid:
            budget = int(per_day * days)
            alert = M.alerts_at_budget(s, budget)
            on_pos = int((alert & (y == 1)).sum())
            fs_c = int((alert & fs).sum())
            red = int((alert & prop).sum())
            res.budgets.append({
                "per_day": per_day, "budget": budget,
                "headline_recall": on_pos / pos if pos else 0.0,
                "fs_recall": fs_c / n_eps if n_eps else 0.0,
                "redundancy_rate": red / on_pos if on_pos else 0.0,
                "friction_efficiency": fs_c / budget if budget else 0.0,
                "primary": per_day == primary,
            })
        pr = next(r for r in res.budgets if r["primary"])
        res.sentence = (
            f"THE GAP: at {pr['per_day']:,} alerts/day your scorer reports "
            f"{pr['headline_recall']:.0%} recall, but only "
            f"{pr['fs_recall']:.0%} of fraud cases are stopped at their first "
            f"attempt, and {pr['redundancy_rate']:.0%} of its correct alerts "
            f"land on entities a {label_delay_days:g}-day blocklist already "
            f"knows. The difference is what your headline metric is "
            f"over-crediting."
        )
    else:
        res.sentence = (
            f"Without a score column this audit reports label structure only: "
            f"{blocklist['recovered_share']:.0%} of your labelled fraud sits "
            f"on entities a {label_delay_days:g}-day blocklist already knows, "
            f"so any transaction-level metric can be up to that share "
            f"'right' without preventing anything. Re-run with "
            f"--map score=<your model column> to measure your own gap."
        )
    return res
