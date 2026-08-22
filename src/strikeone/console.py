"""Strike One console — scoring service + live counters.

Self-contained: stdlib HTTP server, one static page, no auth, no database,
no cloud. Every displayed number is computed at request time from the
replay parquet (built by scripts/stage6_prepare_replay.py) and the frozen
Stage 4 config. Nothing is hardcoded in the UI: Stage 7 points --data at a
holdout-derived file and the same console reports holdout numbers.

Run: uv run python -m strikeone.console [--data PATH] [--port 8777]
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
        self.iso_x = np.array(self.frozen["calibration"]["isotonic_x"])
        self.iso_y = np.array(self.frozen["calibration"]["isotonic_y"])

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
    def stream(self, start: int, limit: int) -> list[dict]:
        rows = []
        for i in range(start, min(start + limit, self.n)):
            r = self.df.iloc[i]
            rows.append({
                "i": i,
                "tid": _js(r["TransactionID"]),
                "day": round(float(r["day"]), 2),
                "uid": r["uid"],
                "amount": round(float(r["amount"]), 2),
                "lane": "lane-1" if r["lane1_flag"] else "lane-2",
                "action": ACTION_NAMES[int(r["action_central"])],
                "p": None if math.isnan(r["p_shipped"]) else round(float(r["p_shipped"]), 4),
                "role": int(r["role"]),
                "y": int(r["y"]),
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
        d = self.df
        agg = d.groupby("uid").agg(
            n=("y", "size"), frauds=("y", "sum"),
            fs=("role", lambda r: int((r == episodes.ROLE_FIRST_STRIKE).sum())),
        )
        good = agg[(agg["fs"] == 1) & (agg["frauds"] >= 3)
                   & (agg["n"] > agg["frauds"])]
        good = good.sort_values("n", ascending=False).head(8)
        return [{"uid": u, "n": int(r["n"]), "frauds": int(r["frauds"])}
                for u, r in good.iterrows()]

    # ------------------------------------------------------ decision object
    def score_tx(self, tid: int) -> dict:
        g = self.df[self.df["TransactionID"] == tid]
        if g.empty:
            return {"error": f"TransactionID {tid} not in replay slice"}
        r = g.iloc[0]
        p = float(r["p_shipped"])
        A = float(r["amount"])
        cp = self.central
        ec = {
            "approve": p * (A + cp["c_h"]),
            "step-up": p * (1 - cp["e"]) * (A + cp["c_h"])
                       + (1 - p) * cp["a"] * cp["m"] * A,
            "block": (1 - p) * cp["m"] * A,
        }
        lane1 = bool(r["lane1_flag"])
        return {
            "TransactionID": _js(r["TransactionID"]),
            "amount": A,
            "lane": "lane-1 (blocklist)" if lane1 else "lane-2 (model)",
            "entity_state_point_in_time": (
                "already flagged — known fraud >= 7 days old on this entity"
                if lane1 else "no prior flags"
            ),
            "calibrated_p": None if lane1 else round(p, 5),
            "expected_cost": None if lane1 else {k: round(v, 3) for k, v in ec.items()},
            "action": "block (by rule)" if lane1
                      else ACTION_NAMES[int(r["action_central"])],
            "cost_params": cp,
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
            "frozen_scorer": self.frozen["lane2_scorer"],
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
                elif u.path == "/api/meta":
                    self._json(replay.meta())
                elif u.path == "/api/counters":
                    self._json(replay.counters(
                        q.get("scorer", "shipped"), q.get("routing", "on"),
                        int(q.get("per_day", 100))))
                elif u.path == "/api/curve":
                    pds = [5, 10, 18, 25, 36, 50, 71, 100, 140, 200, 280, 400, 500]
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
                                             int(q.get("limit", 200))))
                elif u.path == "/api/entity":
                    self._json(replay.entity(q["uid"]))
                elif u.path == "/api/featured":
                    self._json(replay.featured())
                elif u.path == "/api/score":
                    self._json(replay.score_tx(int(q["tid"])))
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
