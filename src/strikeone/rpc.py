"""python -m strikeone.rpc — the TUI's backend.

Newline-delimited JSON-RPC over stdin/stdout: no HTTP, no ports, works
fully offline. The Python CLI stays independently usable; this process is
only ever a child of the Ink app.

  request : {"id": 1, "method": "init", "params": {...}}\n
  response: {"id": 1, "result": {...}}\n  or  {"id": 1, "error": "..."}\n
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from strikeone import audit as audit_mod
from strikeone import contract, entity as ent_mod, episodes, examples
from strikeone import metrics as M
from strikeone import policy_engine
from strikeone import route as route_mod


class Session:
    def __init__(self):
        self.df = None
        self.mapping = None
        self.audit_res = None
        self._arrays = None

    # ------------------------------------------------------------ init
    def init(self, p):
        if p.get("example"):
            raw, m = examples.resolve(p["example"])
        else:
            from pathlib import Path as _P
            if p.get("map"):
                m = contract.Mapping(
                    columns=p["map"],
                    label_delay_days=float(p.get("delay", 7.0)),
                    source=p["source"],
                )
            else:
                # honour the persisted mapping, next to the source or in cwd
                for cand in (_P(p["source"]).parent / contract.CONFIG_FILE,
                             _P(contract.CONFIG_FILE)):
                    if cand.exists():
                        m = contract.Mapping.load(cand)
                        m.source = p["source"]
                        break
                else:
                    raise RuntimeError(
                        "no column mapping found: create one with "
                        "`strikeone check <file> --map ... --save-config` "
                        "(looked for .strikeone.toml beside the file and "
                        "in the working directory)"
                    )
            raw = contract.read_source(p["source"], query=p.get("query"),
                                       table=p.get("table"))
        if p.get("delay") is not None:
            m.label_delay_days = float(p["delay"])
        self.df = contract.apply_mapping(raw, m)
        self.mapping = m
        self.audit_res = None
        self._arrays = None
        return self.meta({})

    def _need(self):
        if self.df is None:
            raise RuntimeError("no dataset loaded; run init first")

    def arrays(self):
        self._need()
        if self._arrays is None:
            d = self.df
            t = d["t"].to_numpy()
            tb = d["transaction_id"].to_numpy()
            ent = d["entity"].to_numpy()
            y = (d["label"].to_numpy().astype(int)
                 if "label" in d.columns else None)
            a = {"t": t, "tb": tb, "ent": ent, "y": y,
                 "amt": d["amount"].to_numpy(dtype=float),
                 "day0": float(t.min()),
                 "days": float((t.max() - t.min()) / 86400.0)}
            if y is not None:
                a["roles"] = episodes.episode_roles(ent, t, y, tiebreak=tb)
                bl = ent_mod.pit_delayed_label_stats(
                    pd.Series(ent), t.astype(np.int64), y, tb,
                    delay_days=self.mapping.label_delay_days, prefix="e")
                a["flag"] = np.nan_to_num(bl["e_fraud_rate"].to_numpy()) > 0
            if "score" in d.columns:
                a["score"] = d["score"].fillna(-np.inf).to_numpy(dtype=float)
            self._arrays = a
        return self._arrays

    # ------------------------------------------------------------ meta
    def meta(self, _p):
        self._need()
        d, m = self.df, self.mapping
        a = self.arrays()
        out = {"rows": len(d), "days": round(a["days"], 1),
               "source": m.source, "delay": m.label_delay_days,
               "has_label": a["y"] is not None,
               "has_score": "score" in d.columns,
               "has_p": "p" in d.columns,
               "entities": int(d["entity"].nunique())}
        if a["y"] is not None:
            out["positives"] = int(a["y"].sum())
            out["episodes"] = int(
                (a["roles"] == episodes.ROLE_FIRST_STRIKE).sum())
            out["lane1_rows"] = int(a["flag"].sum())
        return out

    def check(self, _p):
        self._need()
        rep = contract.check(self.df, self.mapping, for_audit=True)
        return {"ok": rep.ok, "errors": rep.errors,
                "warnings": rep.warnings, "stats": rep.stats}

    def audit(self, _p):
        self._need()
        if self.audit_res is None:
            self.audit_res = audit_mod.audit(
                self.df, label_delay_days=self.mapping.label_delay_days)
        r = self.audit_res
        return {"stats": r.stats, "blocklist": r.blocklist,
                "headline": r.headline, "budgets": r.budgets,
                "sentence": r.sentence}

    def route_curve(self, _p):
        self._need()
        res = route_mod.route(self.df,
                              label_delay_days=self.mapping.label_delay_days)
        return {"lane1": res.lane1, "curve": res.curve}

    def policy(self, p):
        self._need()
        p = dict(p or {})
        want_grid = bool(p.pop("grid", False))
        res = policy_engine.policy(self.df, p, grid=want_grid)
        return {"params": res.params, "mix": res.mix, "costs": res.costs,
                "worst_corner": res.worst_corner,
                "ranges": policy_engine.DECLARED_RANGES}

    # --------------------------------------------------------- screens
    def stream(self, p):
        a = self.arrays()
        if a["y"] is None or "score" not in a:
            raise RuntimeError("stream needs labels and a score column")
        per_day = int(p.get("per_day", 0)) or None
        if per_day is None:
            aud = self.audit({})
            per_day = next(
                (b["per_day"] for b in aud["budgets"] if b["primary"]), 10)
        budget = int(per_day * max(a["days"], 1))
        lane2 = ~a["flag"]
        s2 = np.where(lane2, a["score"], -np.inf)
        alert = M.alerts_at_budget(s2, min(budget, int(lane2.sum())))
        fs = a["roles"] == episodes.ROLE_FIRST_STRIKE
        events = np.flatnonzero(alert | a["flag"])
        start, limit = int(p.get("start", 0)), int(p.get("limit", 60))
        rows = []
        for i in events[start:start + limit]:
            rows.append({
                "day": round(float((a["t"][i] - a["day0"]) / 86400), 2),
                "amount": round(float(a["amt"][i]), 2),
                "entity": str(a["ent"][i]),
                "lane": "auto-block" if a["flag"][i] else "review",
                "caught_fs": bool(fs[i] and (alert[i] or a["flag"][i])),
                "role": int(a["roles"][i]),
            })
        return {"per_day": per_day, "n_events": int(len(events)),
                "rows": rows}

    def featured(self, _p):
        a = self.arrays()
        if a["y"] is None:
            raise RuntimeError("featured cases need labels")
        d = pd.DataFrame({"e": a["ent"], "y": a["y"],
                          "fs": a["roles"] == episodes.ROLE_FIRST_STRIKE})
        agg = d.groupby("e").agg(n=("y", "size"), frauds=("y", "sum"),
                                 fs=("fs", "sum"))
        # deterministic curation: one clear first strike, several later
        # attempts, small enough to read as a story; prefer fully-resolved
        # entity ids (no pooled 'nan' component)
        for min_f, max_n, legit, resolved in [
            (3, 24, True, True), (2, 24, True, True), (3, 40, True, False),
            (2, 999999, False, False), (1, 999999, False, False),
        ]:
            good = agg[(agg["fs"] == 1) & (agg["frauds"] >= min_f)
                       & (agg["n"] <= max_n)]
            if legit:  # the story needs quiet purchases before the strike
                good = good[good["n"] >= good["frauds"] + 2]
            if resolved:
                good = good[~good.index.astype(str).str.contains("nan")]
            if len(good) >= 5:
                break
        good = good.sort_values(["frauds", "n"], ascending=False).head(10)
        out = [{"entity": str(e), "n": int(r["n"]), "frauds": int(r["frauds"])}
               for e, r in good.iterrows()]
        assert all(x["frauds"] >= 1 for x in out), \
            "featured selection produced a fraud-free entity"
        return out

    def case(self, p):
        a = self.arrays()
        eid = p["entity"]
        idx = np.flatnonzero(a["ent"] == eid)
        rows = [{"day": round(float((a["t"][i] - a["day0"]) / 86400), 2),
                 "amount": round(float(a["amt"][i]), 2),
                 "label": int(a["y"][i]) if a["y"] is not None else None,
                 "role": int(a["roles"][i]) if a["y"] is not None else 0}
                for i in idx]
        return {"entity": eid, "rows": rows}


def main():
    sess = Session()
    methods = {"init": sess.init, "meta": sess.meta, "check": sess.check,
               "audit": sess.audit, "route_curve": sess.route_curve,
               "policy": sess.policy, "stream": sess.stream,
               "featured": sess.featured, "case": sess.case,
               "ping": lambda _p: {"pong": True}}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            fn = methods[req["method"]]
            out = {"id": req.get("id"), "result": fn(req.get("params") or {})}
        except Exception as e:  # noqa: BLE001 — surfaced to the TUI
            out = {"id": req.get("id") if isinstance(req, dict) else None,
                   "error": str(e)}
        sys.stdout.write(json.dumps(out, default=float) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
