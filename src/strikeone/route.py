"""`strikeone route` — wrap any scorer with the two-lane routing.

Lane 1: entity has a confirmed fraud at least `label_delay_days` old
        -> block by rule, no review consumed. The blocklist source is
        either the data's own labels (retrospective) or a caller-supplied
        entity blocklist file (prospective).
Lane 2: everything else -> ranked by the caller's score.

With labels present, the measured lift across the capacity curve is
reported: first-hit recall with and without the lane. This is "the
routing protects any scorer" as a tool rather than a claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strikeone import entity as ent_mod
from strikeone import episodes
from strikeone import metrics as M
from strikeone.audit import _budget_grid


@dataclass
class RouteResult:
    lane1: dict
    curve: list = field(default_factory=list)
    decisions: pd.DataFrame | None = None

    def to_json(self) -> str:
        return json.dumps({"lane1": self.lane1, "curve": self.curve},
                          indent=2, default=float)

    def to_text(self) -> str:
        L = ["STRIKE ONE ROUTE"]
        l1 = self.lane1
        L.append(f"  lane 1 auto-blocks {l1['rows']:,} transactions "
                 f"({l1['row_share']:.2%}) on {l1['entities']:,} known "
                 f"entities, consuming no reviews")
        if "legit_blocked" in l1:
            L.append(f"  of those, {l1['legit_blocked']:,} are labelled "
                     "legitimate: the standing policy's own cost, counted")
        if self.curve:
            L.append("")
            L.append("MEASURED LIFT, FIRST-STRIKE RECALL "
                     "(same scorer, lane on vs off)")
            L.append("  alerts/day   lane OFF   lane ON     lift")
            for r in self.curve:
                L.append(f"  {r['per_day']:>9,}   {r['fs_recall_off']:>7.1%}"
                         f"   {r['fs_recall_on']:>7.1%}   {r['lift']:>5.2f}x")
        return "\n".join(L)


def route(
    df: pd.DataFrame,
    label_delay_days: float = 7.0,
    blocklist_entities: set | None = None,
) -> RouteResult:
    df = df.sort_values(["t", "transaction_id"]).reset_index(drop=True)
    t = df["t"].to_numpy()
    tb = df["transaction_id"].to_numpy()
    ent = df["entity"].to_numpy()
    has_labels = "label" in df.columns and df["label"].notna().all()

    if blocklist_entities is not None:
        flag = pd.Series(ent).isin(blocklist_entities).to_numpy()
        src = f"caller-supplied blocklist ({len(blocklist_entities):,} entities)"
    elif has_labels:
        y = df["label"].to_numpy().astype(int)
        bl = ent_mod.pit_delayed_label_stats(
            pd.Series(ent), t.astype(np.int64), y, tb,
            delay_days=label_delay_days, prefix="e")
        flag = np.nan_to_num(bl["e_fraud_rate"].to_numpy()) > 0
        src = f"labels with a {label_delay_days:g}-day delay"
    else:
        raise ValueError("routing needs labels or --blocklist <file of "
                         "entity ids>: there is nothing to route on")

    lane1 = {"rows": int(flag.sum()),
             "row_share": float(flag.mean()),
             "entities": int(pd.Series(ent[flag]).nunique()),
             "source": src}
    decisions = pd.DataFrame({
        "transaction_id": df["transaction_id"],
        "lane": np.where(flag, "auto-block", "score"),
    })
    res = RouteResult(lane1=lane1, decisions=decisions)

    if has_labels:
        y = df["label"].to_numpy().astype(int)
        lane1["legit_blocked"] = int((flag & (y == 0)).sum())
        if "score" in df.columns and df["score"].notna().any():
            s = df["score"].fillna(-np.inf).to_numpy(dtype=float)
            roles = episodes.episode_roles(ent, t, y, tiebreak=tb)
            fs = roles == episodes.ROLE_FIRST_STRIKE
            n_eps = int(fs.sum())
            days = float((t.max() - t.min()) / 86400.0)
            grid, primary = _budget_grid(len(df), days, int(y.sum()))
            lane2 = ~flag
            s_l2 = np.where(lane2, s, -np.inf)
            for per_day in grid:
                b = int(per_day * days)
                off = M.alerts_at_budget(s, b)
                on = M.alerts_at_budget(s_l2, min(b, int(lane2.sum())))
                r_off = float(off[fs].mean()) if n_eps else 0.0
                r_on = (float(on[fs].mean()) + float(flag[fs].mean())
                        if n_eps else 0.0)
                res.curve.append({
                    "per_day": per_day, "budget": b,
                    "fs_recall_off": r_off, "fs_recall_on": r_on,
                    "lift": (r_on / r_off) if r_off > 0 else float("inf"),
                    "primary": per_day == primary,
                })
    return res
