"""`strikeone policy` — the cost-derived three-action policy.

Needs a CALIBRATED probability column (`--map p=<col>`); calibrate first,
that step is yours. Economics come in as declared ranges, recommendations
come out as {approve, step-up, block} with the sensitivity grid over the
range corners and the corner where a cost-derived policy stops beating a
plain fixed threshold, shown rather than hidden.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strikeone import metrics as M

DECLARED_RANGES = {"m": [0.05, 0.15, 0.25], "a": [0.05, 0.125, 0.20],
                   "e": [0.2, 0.775, 0.95], "c_h": [15.0, 30.0, 60.0],
                   "s": [0.0, 0.5, 1.0]}
CENTRAL = {"m": 0.15, "a": 0.125, "e": 0.775, "c_h": 30.0, "s": 0.0}
# The e floor was widened 0.6 -> 0.2 AFTER the second-access results were
# seen, because a reviewer challenged the original floor (the grid never
# tested the assumption the cost result rests on). Stated, not slipped:
# see reports/stage8/e_sweep_summary.json. The frozen central point and
# the shipped default policy are unchanged.
# s = liability shifted to the issuer on successful step-up authentication.
# DEFAULT 0: the shipped policy at default is bit-identical to the frozen
# config (asserted by test). The sweep explores s > 0; it never changes the
# shipped default. India caveat: RBI mandates AFA domestically, so
# liability-shift dynamics differ from optional-3DS markets. Stated only.


@dataclass
class PolicyResult:
    params: dict
    mix: dict
    costs: dict
    grid: list = field(default_factory=list)
    worst_corner: dict | None = None
    decisions: pd.DataFrame | None = None

    def to_json(self) -> str:
        from strikeone.contract import json_safe
        return json.dumps(json_safe({"params": self.params, "mix": self.mix,
                                     "costs": self.costs, "grid": self.grid,
                                     "worst_corner": self.worst_corner}),
                          indent=2, default=float)

    def to_text(self) -> str:
        L = ["STRIKE ONE POLICY"]
        p = self.params
        L.append(f"  economics: margin {p['m']:.0%}, abandonment {p['a']:.1%}, "
                 f"step-up efficacy {p['e']:.0%}, chargeback handling "
                 f"{p['c_h']:g} (amount units)")
        if p.get("s", 0):
            L.append(f"  liability shift on successful step-up: {p['s']:.0%}")
        m = self.mix
        L.append(f"  recommended mix: approve {m['pct'][0]:.1f}%  "
                 f"ask-to-verify {m['pct'][1]:.1f}%  block {m['pct'][2]:.1f}%")
        c = self.costs
        if c.get("policy") is not None:
            L.append(f"  realized cost: policy {c['policy']:,.0f} vs "
                     f"approve-all {c['approve_all']:,.0f} vs best fixed "
                     f"threshold {c['fixed_threshold']:,.0f}")
            L.append(f"  savings vs approve-all: {c['savings']:.1%}")
        if self.worst_corner:
            w = self.worst_corner
            L.append(f"  honest corner: at m={w['m']}, a={w['a']}, e={w['e']}, "
                     f"c_h={w['c_h']}, s={w.get('s', 0)} the cost-derived "
                     "policy's edge over a "
                     f"fixed threshold is {w['edge_vs_fixed']:+.2%} of "
                     "approve-all cost, its weakest point in the declared "
                     "ranges. Shown, not hidden.")
        return "\n".join(L)


def _clamp(params: dict) -> M.CostParams:
    out = {}
    for k, rng in DECLARED_RANGES.items():
        v = float(params.get(k, CENTRAL[k]))
        out[k] = min(max(v, rng[0]), rng[-1])
    return M.CostParams(**out)


def policy(df: pd.DataFrame, params: dict | None = None,
           grid: bool = True) -> PolicyResult:
    if "p" not in df.columns or df["p"].isna().all():
        raise ValueError(
            "policy needs a calibrated probability column: --map p=<column>. "
            "Calibrate your scorer first (isotonic on a chronologically "
            "earlier slice); this package will not do it for you on the "
            "evaluation data."
        )
    prm = _clamp(params or {})
    pcol = df["p"].to_numpy(dtype=float)
    if np.isnan(pcol).any():
        raise ValueError(
            f"{int(np.isnan(pcol).sum()):,} rows have a missing p; policy "
            "prices every row and refuses to guess. Fill or filter first.")
    if pcol.min() < -1e-9 or pcol.max() > 1 + 1e-9:
        raise ValueError(
            f"p ranges [{pcol.min():.3g}, {pcol.max():.3g}] - that is not "
            "a calibrated probability. A raw model score priced as a "
            "probability produces nonsense costs; calibrate on a "
            "chronologically earlier slice first (isotonic or Platt), "
            "then map the calibrated column with --map p=<column>.")
    amt = df["amount"].to_numpy(dtype=float)
    ec = M.expected_cost_matrix(pcol, amt, prm)
    act = ec.argmin(axis=1)
    mix = np.bincount(act, minlength=3)
    res = PolicyResult(
        params=prm.__dict__,
        mix={"approve": int(mix[0]), "step_up": int(mix[1]),
             "block": int(mix[2]),
             "pct": [round(float(v) / len(act) * 100, 1) for v in mix]},
        costs={},
        decisions=pd.DataFrame({
            "transaction_id": df["transaction_id"],
            "action": np.array(["approve", "step-up", "block"])[act],
            "p": pcol,
        }),
    )

    has_labels = "label" in df.columns and df["label"].notna().all()
    if has_labels:
        y = df["label"].to_numpy().astype(int)

        # Best fixed threshold (block above tau, approve below), for any
        # cost corner. The threshold cost is linear in (m, c_h):
        #   cost(tau) = sum_{p<tau} y*(A+c_h) + sum_{p>=tau} (1-y)*m*A
        # so precompute, per candidate tau, the three aggregates once and
        # the per-corner search is O(#taus) instead of O(#taus * n).
        taus = np.unique(np.quantile(pcol, np.linspace(0, 1, 101)))
        order = np.argsort(pcol, kind="stable")
        p_s, y_s, a_s = pcol[order], y[order], amt[order]
        cut = np.searchsorted(p_s, taus, side="left")
        c_ya = np.concatenate([[0.0], np.cumsum(y_s * a_s)])
        c_y = np.concatenate([[0.0], np.cumsum(y_s)])
        c_la = np.concatenate([[0.0], np.cumsum((1 - y_s) * a_s)])
        t_fraud_amt = c_ya[cut]                    # approved fraud amount
        t_fraud_cnt = c_y[cut]                     # approved fraud count
        t_legit_amt = c_la[-1] - c_la[cut]         # blocked legit amount

        def fixed_cost(pr):
            return float(np.min(t_fraud_amt + pr.c_h * t_fraud_cnt
                                + pr.m * t_legit_amt))

        c_pol = float(M.realized_cost(y, act, amt, prm).sum())
        c_app = float(M.realized_cost(y, np.zeros(len(y)), amt, prm).sum())
        res.costs = {"policy": c_pol, "approve_all": c_app,
                     "fixed_threshold": fixed_cost(prm),
                     "savings": (c_app - c_pol) / c_app if c_app else 0.0}
        if not grid:
            return res
        worst = None
        for m_, a_, e_, ch_, s_ in itertools.product(*DECLARED_RANGES.values()):
            pr = M.CostParams(m=m_, a=a_, e=e_, c_h=ch_, s=s_)
            eci = M.expected_cost_matrix(pcol, amt, pr)
            ai = eci.argmin(axis=1)
            ci = float(M.realized_cost(y, ai, amt, pr).sum())
            cf = fixed_cost(pr)
            ca = float(M.realized_cost(y, np.zeros(len(y)), amt, pr).sum())
            edge = (cf - ci) / ca if ca else 0.0
            res.grid.append({"m": m_, "a": a_, "e": e_, "c_h": ch_, "s": s_,
                             "cost_policy": ci, "cost_fixed": cf,
                             "edge_vs_fixed": edge})
            if worst is None or edge < worst["edge_vs_fixed"]:
                worst = res.grid[-1]
        res.worst_corner = worst
    else:
        res.costs = {"policy": None,
                     "note": "no labels: recommendations only, no realized "
                             "cost. Add --map label=<col> to price them."}
    return res
