"""Strike One console — scoring service + live counters.

Self-contained: stdlib HTTP server, one static page, no auth, no database,
no cloud. Every displayed number is computed at request time from the
replay parquet (built by scripts/stage6_prepare_replay.py) and the frozen
Stage 4 config. Nothing is hardcoded in the UI: Stage 7 points --data at a
holdout-derived file and the same console reports holdout numbers.

Run: uv run python extras/console/console.py [--data PATH] [--port 8777]
"""

from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from strikeone import config, episodes
from strikeone import metrics as M

STATIC = Path(__file__).parent / "console_static"

ACTION_NAMES = {0: "approve", 1: "step-up", 2: "block"}
APPROVE_CODE = 0
# capacity grid capped at 200/day: above that the operating point reviews
# >6% of all traffic, which no risk team does
PER_DAY_GRID = [5, 10, 18, 25, 36, 50, 71, 100, 140, 200]


def _js(v):
    """JSON-safe scalar."""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


class Replay:
    def __init__(self, data_path: Path, frozen_path: Path):
        self.df = pd.read_parquet(data_path)
        self.data_path = str(data_path)
        self.frozen = json.loads(frozen_path.read_text())
        self.central = self.frozen["cost_params_central"]
        self.ranges = self.frozen["cost_params_ranges"]
        self.iso_x = np.array(self.frozen["calibration"]["isotonic_x"])
        self.iso_y = np.array(self.frozen["calibration"]["isotonic_y"])
        # committed Stage 4 grid (validation-priced): used only to surface
        # the corner where our advantage vanishes; never recomputed here
        grid_path = config.REPORTS / "stage4" / "episode_cost_grid.csv"
        self.grid = pd.read_csv(grid_path) if grid_path.exists() else None

        d = self.df
        self.n = len(d)
        self.y = d["y"].to_numpy()
        self.role = d["role"].to_numpy()
        self.flag = d["lane1_flag"].to_numpy()
        self.amount = d["amount"].to_numpy()
        self.fs = self.role == episodes.ROLE_FIRST_STRIKE
        self.prop = self.role == episodes.ROLE_PROPAGATED
        self.n_days = int(d["day_idx"].nunique())
        self.n_episodes = int(self.fs.sum())
        self.scores = {"shipped": d["s_shipped"].to_numpy(),
                       "headline": d["s_headline"].to_numpy()}
        self.lane1 = {
            "n": int(self.flag.sum()),
            "redundant_covered": int((self.flag & self.prop).sum()),
            "legit_blocked": int((self.flag & (self.y == 0)).sum()),
            "fs_in_lane1": int((self.flag & self.fs).sum()),
        }
        self._orders = {}
        for scorer in ("shipped", "headline"):
            for routing in ("on", "off"):
                pop = ~self.flag if routing == "on" else np.ones(self.n, bool)
                idx = np.flatnonzero(pop)
                order = idx[np.argsort(-self.scores[scorer][idx], kind="stable")]
                self._orders[(scorer, routing)] = {
                    "order": order,
                    "cum_fs": np.concatenate([[0], np.cumsum(self.fs[order])]),
                    "cum_prop": np.concatenate([[0], np.cumsum(self.prop[order])]),
                    "cum_fp": np.concatenate([[0], np.cumsum(self.y[order] == 0)]),
                }
        latency_file = config.REPORTS / "stage6" / "latency.json"
        self.latency = (json.loads(latency_file.read_text())
                        if latency_file.exists() else None)

    # ------------------------------------------------------------ counters
    def counters(self, scorer: str, routing: str, per_day: int) -> dict:
        if scorer == "blocklist":
            alerts_fs = self.lane1["fs_in_lane1"]
            red = self.lane1["redundant_covered"]
            fp = self.lane1["legit_blocked"]
            n_alerts = self.lane1["n"]
            budget = n_alerts
        else:
            o = self._orders[(scorer, routing)]
            budget = min(per_day * self.n_days, len(o["order"]))
            alerts_fs = int(o["cum_fs"][budget])
            red = int(o["cum_prop"][budget])
            fp = int(o["cum_fp"][budget])
            n_alerts = budget
            if routing == "on":
                alerts_fs += self.lane1["fs_in_lane1"]
        prop_total = int(self.prop.sum())
        prop_caught = red + (self.lane1["redundant_covered"]
                             if routing == "on" and scorer != "blocklist" else 0)
        return {
            "scorer": scorer, "routing": routing, "per_day": per_day,
            "n_days": self.n_days, "budget": budget, "n_alerts": n_alerts,
            "fs_catches": alerts_fs, "n_episodes": self.n_episodes,
            "fs_recall": round(alerts_fs / self.n_episodes, 4),
            "redundant_alerts": red,
            "false_positives": fp,
            "prop_recall_total": round(prop_caught / prop_total, 4),
            "lane1": self.lane1 if (routing == "on" and scorer != "blocklist")
                     else None,
        }

    def curve(self, scorer: str, routing: str, per_days: list[int]) -> list:
        return [
            {"per_day": p,
             "fs_recall": self.counters(scorer, routing, p)["fs_recall"]}
            for p in per_days
        ]

    # ------------------------------------------------------------- stream
    def stream(self, start: int, limit: int, mode: str = "all") -> list[dict]:
        """mode='action': only non-approve decisions and lane-1 routings —
        the rows where something happens."""
        if mode == "action":
            m = (self.df["action_central"] != APPROVE_CODE) | self.df["lane1_flag"]
            frame = self.df[m]
        else:
            frame = self.df
        rows = []
        for i in range(start, min(start + limit, len(frame))):
            r = frame.iloc[i]
            action = ACTION_NAMES[int(r["action_central"])]
            rows.append({
                "i": i,
                "tid": _js(r["TransactionID"]),
                "day": round(float(r["day"]), 2),
                "uid": r["uid"],
                "amount": round(float(r["amount"]), 2),
                "lane": "lane-1" if r["lane1_flag"] else "lane-2",
                "action": action,
                "p": None if math.isnan(r["p_shipped"]) else round(float(r["p_shipped"]), 4),
                "role": int(r["role"]),
                "y": int(r["y"]),
                # the moment the system exists for: a first strike, stopped
                "caught_fs": bool(
                    int(r["role"]) == episodes.ROLE_FIRST_STRIKE
                    and (action != "approve" or bool(r["lane1_flag"]))
                ),
            })
        return rows

    # ------------------------------------------------------------- entity
    def entity(self, uid: str) -> dict:
        g = self.df[self.df["uid"] == uid]
        return {
            "uid": uid,
            "n": len(g),
            "rows": [
                {"tid": _js(r["TransactionID"]), "day": round(float(r["day"]), 3),
                 "amount": round(float(r["amount"]), 2), "y": int(r["y"]),
                 "role": int(r["role"]),
                 "action": ACTION_NAMES[int(r["action_central"])],
                 "lane": "lane-1" if r["lane1_flag"] else "lane-2"}
                for _, r in g.iterrows()
            ],
        }

    @lru_cache(maxsize=1)
    def featured(self) -> list:
        """Curated real episodes, deterministic selection rule (no hardcoded
        ids): exactly one first strike in the slice, several propagated
        positives after it, and at least one legitimate row for contrast.
        Ordered by fraud count then amount at stake. Falls back to looser
        thresholds rather than ever returning a fraud-free entity."""
        d = self.df
        agg = d.groupby("uid").agg(
            n=("y", "size"), frauds=("y", "sum"), amt=("amount", "sum"),
            fs=("role", lambda r: int((r == episodes.ROLE_FIRST_STRIKE).sum())),
        )
        for min_frauds, need_legit, need_resolved in [
            (4, True, True), (3, True, True), (4, True, False),
            (3, True, False), (2, False, False), (1, False, False),
        ]:
            good = agg[(agg["fs"] == 1) & (agg["frauds"] >= min_frauds)]
            if need_resolved:  # prefer fully-resolved uids (no pooled "nan")
                good = good[~good.index.str.contains("_nan")]
            if need_legit:
                good = good[good["n"] > good["frauds"]]
            if len(good) >= 5:
                break
        good = good.sort_values(["frauds", "amt"], ascending=False).head(8)
        out = [{"uid": u, "n": int(r["n"]), "frauds": int(r["frauds"])}
               for u, r in good.iterrows()]
        assert out and all(e["frauds"] >= 1 for e in out), (
            "featured-episode selection produced a fraud-free entity"
        )
        return out

    # -------------------------------------------------------------- policy
    def _clamp_params(self, q: dict) -> M.CostParams:
        """Operator economics, clamped to the DECLARED ranges. Policy inputs
        only: model, calibration, and config stay frozen."""
        def g(name, key):
            lo, hi = self.ranges[key][0], self.ranges[key][-1]
            v = float(q.get(name, self.central[key]))
            return min(max(v, lo), hi)
        return M.CostParams(m=g("m", "m"), a=g("a", "a"),
                            e=g("e", "e"), c_h=g("c_h", "c_h"))

    def policy(self, q: dict) -> dict:
        prm = self._clamp_params(q)
        lane2 = ~self.flag
        p = self.df["p_shipped"].to_numpy()[lane2]
        amt2 = self.amount[lane2]
        y2 = self.y[lane2]
        ec = M.expected_cost_matrix(p, amt2, prm)
        act = ec.argmin(axis=1)
        cost2 = float(M.realized_cost(y2, act, amt2, prm).sum())
        y1, a1 = self.y[self.flag], self.amount[self.flag]
        cost1 = float(M.realized_cost(y1, np.full(len(y1), 2), a1, prm).sum())
        cost = cost1 + cost2
        approve_all = float(M.realized_cost(
            self.y, np.zeros(self.n), self.amount, prm).sum())
        bl_only = cost1 + float(M.realized_cost(
            y2, np.zeros(len(y2)), amt2, prm).sum())
        mix = np.bincount(act, minlength=3)
        # nearest committed grid corner: does the headline system win there?
        corner = None
        if self.grid is not None:
            g = self.grid
            dist = ((g["m"] - prm.m).abs() / .2 + (g["a"] - prm.a).abs() / .15
                    + (g["e"] - prm.e).abs() / .35 + (g["c_h"] - prm.c_h).abs() / 45)
            row = g.loc[dist.idxmin()]
            corner = {
                "delta_per_1k": float(row["delta_headline_minus_ours_per_1k"]),
                "headline_cheaper_here": bool(
                    row["delta_headline_minus_ours_per_1k"] < 0),
                "corner": {k: float(row[k]) for k in ["m", "a", "e", "c_h"]},
            }
        return {
            "params": prm.__dict__, "ranges": self.ranges,
            "mix": {"approve": int(mix[0]), "step_up": int(mix[1]),
                    "block": int(mix[2]),
                    "pct": [round(float(v) / len(act) * 100, 1) for v in mix]},
            "cost_policy": round(cost, 0),
            "cost_approve_all": round(approve_all, 0),
            "cost_blocklist_only": round(bl_only, 0),
            "savings_vs_approve_all": round((approve_all - cost) / approve_all, 4),
            "validation_grid_corner": corner,
        }

    # ------------------------------------------------------ decision object
    def score_tx(self, tid: int, q: dict | None = None) -> dict:
        g = self.df[self.df["TransactionID"] == tid]
        if g.empty:
            return {"error": f"TransactionID {tid} not in replay slice"}
        r = g.iloc[0]
        p = float(r["p_shipped"])
        A = float(r["amount"])
        prm = self._clamp_params(q or {})
        m, a, e, ch = prm.m, prm.a, prm.e, prm.c_h
        ec = {
            "approve": p * (A + ch),
            "step_up": p * (1 - e) * (A + ch) + (1 - p) * a * m * A,
            "block": (1 - p) * m * A,
        }
        # risk levels at which the recommendation changes, at this amount
        p_su = a * m * A / (e * (A + ch) + a * m * A)
        p_bl = m * A * (1 - a) / ((1 - e) * (A + ch) + m * A * (1 - a))
        lane1 = bool(r["lane1_flag"])
        action = (2 if lane1
                  else int(np.argmin([ec["approve"], ec["step_up"], ec["block"]])))
        # entity context: what the system could know at decision time
        same = self.df[self.df["uid"] == r["uid"]]
        before = same[same["t"] < r["t"]]
        return {
            "TransactionID": _js(r["TransactionID"]),
            "amount": A,
            "uid": r["uid"],
            "lane": "auto-blocked (already known)" if lane1 else "scored by model",
            "lane_technical": "lane-1 (blocklist)" if lane1 else "lane-2 (model)",
            "entity_state_point_in_time": (
                "this customer identity already has a confirmed fraud at least "
                "7 days old" if lane1 else "no prior confirmed fraud on this "
                "customer identity"
            ),
            "entity_prior_txns_in_window": int(len(before)),
            "risk": None if lane1 else round(p, 5),
            "expected_cost": None if lane1 else {k: round(v, 3) for k, v in ec.items()},
            "action": "block (by rule)" if lane1 else ACTION_NAMES[action],
            "would_change": None if lane1 else {
                "step_up_if_risk_above": round(float(p_su), 5),
                "block_if_risk_above": round(float(p_bl), 5),
            },
            "cost_params": prm.__dict__,
            "ground_truth_role_EVALUATION_ONLY": {
                0: "legit", 1: "first strike", 2: "propagated"
            }[int(r["role"])],
        }

    def meta(self) -> dict:
        d = self.df
        return {
            "data_path": self.data_path,
            "rows": self.n, "n_days": self.n_days,
            "day_range": [int(d["day_idx"].min()), int(d["day_idx"].max())],
            "n_episodes": self.n_episodes,
            "positives": int(self.y.sum()),
            "lane1": self.lane1,
            "central_params": self.central,
            "param_ranges": self.ranges,
            "frozen_scorer": self.frozen["lane2_scorer"],
            "frozen_hash": self.frozen.get("lane2_model_sha256", "")[:12],
            "latency": self.latency,
        }


def make_handler(replay: Replay):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, default=_js).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    body = (STATIC / "index.html").read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path.startswith("/fonts/"):
                    f = (STATIC / "fonts" / Path(u.path).name).resolve()
                    if f.parent != (STATIC / "fonts").resolve() or not f.exists():
                        self._json({"error": "not found"}, 404)
                        return
                    body = f.read_bytes()
                    ctype = ("font/woff2" if f.suffix == ".woff2"
                             else "text/plain; charset=utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "max-age=86400")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/meta":
                    self._json(replay.meta())
                elif u.path == "/api/counters":
                    self._json(replay.counters(
                        q.get("scorer", "shipped"), q.get("routing", "on"),
                        int(q.get("per_day", 100))))
                elif u.path == "/api/curve":
                    pds = PER_DAY_GRID
                    self._json({
                        "per_days": pds,
                        "series": {
                            f"{s}/{r}": [c["fs_recall"] for c in
                                         replay.curve(s, r, pds)]
                            for s in ("shipped", "headline") for r in ("on", "off")
                        },
                    })
                elif u.path == "/api/stream":
                    self._json(replay.stream(int(q.get("start", 0)),
                                             int(q.get("limit", 200)),
                                             q.get("mode", "all")))
                elif u.path == "/api/entity":
                    self._json(replay.entity(q["uid"]))
                elif u.path == "/api/featured":
                    self._json(replay.featured())
                elif u.path == "/api/score":
                    self._json(replay.score_tx(int(q["tid"]), q))
                elif u.path == "/api/policy":
                    self._json(replay.policy(q))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001 — surface to the client
                self._json({"error": str(e)}, 500)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data",
                    default=str(config.DATA_PROCESSED / "console_replay.parquet"))
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()

    # the console never opens the sealed holdout itself
    log = config.HOLDOUT_ACCESS_LOG.read_text() if config.HOLDOUT_ACCESS_LOG.exists() else ""
    print(f"holdout access log entries at startup: {len(log.splitlines())}")

    replay = Replay(Path(args.data),
                    config.REPORTS / "stage4" / "shipped_system_frozen.json")
    m = replay.meta()
    print(f"replay: {m['rows']} rows, days {m['day_range'][0]}-{m['day_range'][1]}, "
          f"{m['n_episodes']} episodes, lane-1 {m['lane1']['n']}")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(replay))
    print(f"Strike One console -> http://127.0.0.1:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
