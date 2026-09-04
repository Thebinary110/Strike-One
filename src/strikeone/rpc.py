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

from strikeone.audit import audit as run_audit
from strikeone import contract, entity as ent_mod, episodes, examples
from strikeone import metrics as M
from strikeone import policy_engine
from strikeone.route import route as run_route


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

    def audit(self, p):
        self._need()
        cap = p.get("capacity")
        if cap is not None:
            cap = float(cap)
        if getattr(self, "_audit_cap", "unset") != cap:
            self.audit_res = None
        if self.audit_res is None:
            self.audit_res = run_audit(
                self.df, label_delay_days=self.mapping.label_delay_days,
                capacity_per_day=cap)
            self._audit_cap = cap
        r = self.audit_res
        return {"stats": r.stats, "blocklist": r.blocklist,
                "headline": r.headline, "budgets": r.budgets,
                "sentence": r.sentence}

    # ----------------------------------------------------- slash commands
    # The TUI's `/why /timeline /compare /evidence /provider` inputs land
    # here. Same rules as the CLI: AI narrates finished evidence, disabled
    # by default, provider failures come back as text, never tracebacks.

    def ai(self, p):
        self._need()
        from strikeone.ai import aiconfig, commands
        from strikeone.ai.providers import ProviderError
        cmd = p.get("cmd")
        if cmd not in ("why", "timeline", "compare"):
            raise ValueError(f"unknown ai command {cmd!r}")
        cfg = aiconfig.AIConfig.load()
        if cfg is None:
            return {"disabled": True, "text":
                    "AI is disabled (the default). Configure it once in "
                    "your shell:\n  strikeone ai setup --provider ollama "
                    "--model <name>\nThen /why /timeline /compare work "
                    "here. /evidence <cmd> <id> needs no model at all."}
        try:
            res = commands.run(cmd, self.df, self.mapping,
                               str(p.get("target", "")), cfg.build())
        except ProviderError as e:
            return {"error_text": f"AI provider unavailable\n{e}\n"
                    "Core panels remain fully available."}
        return {"text": res["rendered"], "model": res["model"],
                "validity": res["validity"],
                "hash": res["evidence_hash"]}

    def evidence(self, p):
        self._need()
        import json as _json

        from strikeone.ai import evidence as ev
        cmd = p.get("cmd")
        if cmd not in ev.BUILDERS:
            raise ValueError(f"unknown evidence command {cmd!r}")
        con = ev.BUILDERS[cmd](self.df, self.mapping,
                               str(p.get("target", "")))
        return {"text": _json.dumps(con, indent=2)}

    # -------------------------------------------------- onboarding wizard
    # The TUI's /onboard flow. Same machinery and gates as the CLI: the
    # scan never auto-accepts label/entity/competing timestamps; every
    # human answer is validated on the real data before acceptance; the
    # file is written only by onboard_finish after all gates pass.

    def onboard_scan(self, p):
        from strikeone import onboard as ob
        source = p["source"]
        raw = contract.read_source(source)
        share = bool(p.get("share_samples"))
        profiles = ob.profile_frame(raw, share_samples=share)
        proposals = ob.heuristic_proposals(profiles)
        model, dropped, ai_note = \
            "heuristic only (no AI provider configured)", [], None
        from strikeone.ai import aiconfig
        cfg = aiconfig.AIConfig.load()
        if cfg is not None:
            from strikeone.ai.providers import ProviderError
            try:
                ai_props, dropped, model = ob.llm_proposals(profiles,
                                                            cfg.build())
                proposals += ai_props
            except ProviderError as e:
                ai_note = f"AI proposer unavailable ({e}); heuristic only"
        decisions = ob.decide(raw, proposals)
        self._ob = {"raw": raw, "profiles": profiles, "share": share,
                    "decisions": decisions, "source": source,
                    "model": model, "dropped": dropped}
        from pathlib import Path as _P
        rows = []
        for t, d in decisions.items():
            rows.append({"target": t, "source": d.source,
                         "status": d.status,
                         "confidence": d.confidence, "method": d.method,
                         "reason": d.reason, "competing": d.competing,
                         "soft": d.validation.get("soft", []),
                         "required": t in ob.REQUIRED})
        pending = [r["target"] for r in rows
                   if r["status"] == "ask"
                   or (r["required"] and r["status"] == "unmapped")]
        return {"rows": rows, "pending": pending, "model": model,
                "ai_note": ai_note, "share_samples": share,
                "toml_exists": _P(contract.CONFIG_FILE).exists()}

    def _ob_state(self):
        ob_state = getattr(self, "_ob", None)
        if ob_state is None:
            raise RuntimeError("no onboarding in progress; run "
                               "/onboard <file> first")
        return ob_state

    def onboard_validate(self, p):
        from strikeone import onboard as ob
        st = self._ob_state()
        target = p["target"]
        src = p["source"]
        if target == "entity" and not isinstance(src, list):
            src = [c.strip() for c in
                   str(src).replace("+", ",").split(",") if c.strip()]
        val = ob.validate_field(target, st["raw"], src)
        if target == "score" and not val["hard"]:
            lb = st["decisions"].get("label")
            if lb is not None and lb.source is not None:
                leak = ob.score_leak_check(
                    st["raw"],
                    src if not isinstance(src, list) else src[0],
                    lb.source if not isinstance(lb.source, list)
                    else lb.source[0])
                if leak and leak not in val["soft"]:
                    val["soft"].append(leak)
        return {"source": src, "hard": val["hard"], "soft": val["soft"]}

    def onboard_accept(self, p):
        from strikeone import onboard as ob
        st = self._ob_state()
        target = p["target"]
        d = st["decisions"][target]
        v = self.onboard_validate(p)
        if v["hard"]:
            raise RuntimeError("; ".join(v["hard"]))
        proposed = d.source if isinstance(d.source, list) else [d.source]
        answered = v["source"] if isinstance(v["source"], list) \
            else [v["source"]]
        d.source = v["source"]
        d.status = "confirmed"
        d.method = d.method if answered == proposed else "user"
        d.validation = {"hard": [], "soft": v["soft"]}
        return {"ok": True, "soft": v["soft"]}

    def onboard_skip(self, p):
        from strikeone import onboard as ob
        st = self._ob_state()
        target = p["target"]
        if target in ob.REQUIRED:
            raise RuntimeError(f"{target} is required and cannot be "
                               "skipped")
        st["decisions"][target] = ob.Decision(target_field=target)
        return {"ok": True}

    def onboard_finish(self, p):
        import json as _json
        from pathlib import Path as _P

        from strikeone import onboard as ob
        st = self._ob_state()
        decisions = st["decisions"]
        missing = [t for t in ob.REQUIRED
                   if decisions[t].status not in ("auto", "confirmed")]
        if missing:
            raise RuntimeError("still unanswered: " + ", ".join(missing))
        delay = float(p.get("delay", 7.0))
        cfg_path = _P(contract.CONFIG_FILE)
        if cfg_path.exists() and not p.get("overwrite"):
            return {"needs_overwrite": str(cfg_path)}
        m = ob.decisions_to_mapping(decisions, delay, st["source"])
        rep = ob.final_gate(st["raw"], m)
        if not rep.ok:
            raise RuntimeError("final contract check refused the mapping: "
                               + "; ".join(rep.errors))
        rec = ob.audit_record(decisions, st["profiles"], delay,
                              st["model"], st["dropped"], st["share"])
        m.save(cfg_path)
        _P(".strikeone.onboarding.json").write_text(
            _json.dumps(rec, indent=2))
        n_auto = sum(1 for d in decisions.values() if d.status == "auto")
        n_conf = sum(1 for d in decisions.values()
                     if d.status == "confirmed")
        self._ob = None
        return {"written": [str(cfg_path), ".strikeone.onboarding.json"],
                "auto": n_auto, "confirmed": n_conf,
                "source": st["source"]}

    def onboard_abort(self, _p):
        self._ob = None
        return {"ok": True}

    def ai_setup(self, p):
        """Provider config from the TUI. Never a secret: api_key_env must
        LOOK like an env var name, and guarded_write refuses any value
        matching a *KEY*/*TOKEN* environment variable's value."""
        import re as _re

        from strikeone.ai import aiconfig
        key_env = p.get("api_key_env") or "OPENAI_API_KEY"
        if not _re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key_env):
            raise RuntimeError(
                f"{key_env!r} does not look like an environment variable "
                "NAME (UPPER_SNAKE_CASE). Never enter the key itself - "
                "export it in your shell and give its name here.")
        cfg = aiconfig.AIConfig(provider=p["provider"],
                                model=p.get("model", ""),
                                base_url=p.get("base_url", ""),
                                api_key_env=key_env,
                                think=p.get("think", ""))
        provider = cfg.build()   # validates provider/base_url combination
        cfg.save()
        return {"text": "written to .strikeone-ai.toml (no secrets: it "
                        "stores the env var's name, not its value)\n\n"
                        + provider.chain_text()}

    def chat(self, p):
        """Free-form questions from the TUI's input box, Claude-Code
        style. Same discipline as every AI feature: the engine builds an
        evidence contract from the CURRENT session's already-computed
        results, the model narrates it, and the citation validator drops
        any number or decision word the contract does not vouch for."""
        from strikeone.ai import aiconfig
        cfg = aiconfig.AIConfig.load()
        if cfg is None:
            return {"disabled": True, "text":
                    "AI is disabled (the default), so free questions are "
                    "off. Enable once:\n  setup ollama <model>\nCommands "
                    "keep working without it - type help."}
        contract = self._overview_contract()
        from strikeone.ai import validator as val_mod
        from strikeone.ai.commands import SYSTEM_PROMPT
        from strikeone.ai.providers import ProviderError
        import json as _json
        question = str(p.get("question", ""))[:500]
        user = ("Task: Answer the user's question about this dataset and "
                "the evaluation results, using ONLY the evidence. If the "
                "evidence cannot answer it, say so in a SUMMARY line "
                "without digits and point at a command (audit, route, "
                "case <id>, why <txn>) that would.\n\n"
                "The evidence contract (your ONLY source of facts):\n"
                + _json.dumps(contract, indent=2)
                + "\n\nThe user's question: " + question)
        try:
            reply = cfg.build().narrate(SYSTEM_PROMPT, user)
        except ProviderError as e:
            return {"error_text": f"AI provider unavailable\n{e}\n"
                    "Commands keep working."}
        v = val_mod.validate(reply.text, contract)
        rendered = val_mod.render(v, contract, reply.model,
                                  reply.provider_label)
        return {"text": rendered, "model": reply.model,
                "validity": v.validity,
                "hash": contract["evidence_hash"]}

    def _overview_contract(self) -> dict:
        """The current session's headline numbers as a hashed, citable
        evidence contract (schema v1.0; command 'chat'). No raw rows."""
        self._need()
        from strikeone.ai import evidence as ev
        meta = self.meta({})
        items = []

        def add(feature, value, source, baseline=None):
            items.append({"id": f"S{len(items) + 1}", "feature": feature,
                          "value": value, "baseline": baseline,
                          "source": source})

        add("rows", int(meta["rows"]), "loaded dataset")
        add("days", float(meta["days"]), "timestamp span")
        add("entities", int(meta["entities"]), "distinct entity keys")
        add("label_delay_days", float(meta["delay"]),
            "declared label maturity assumption")
        if meta.get("has_label"):
            add("labelled_fraud_rows", int(meta["positives"]),
                "label column")
            add("fraud_cases", int(meta["episodes"]),
                "entities' first labelled transactions (episodes)")
            aud = self.audit({})
            st, bl = aud["stats"], aud["blocklist"]
            if st.get("stickiness") is not None:
                add("label_stickiness_x_base_rate",
                    round(float(st["stickiness"]), 1),
                    "P(label | earlier label on entity) / base rate")
            add("blocklist_recovered_share",
                round(float(bl["recovered_share"]), 4),
                f"plain blocklist at the {meta['delay']:g}-day delay")
            add("blocklist_flags", int(bl.get("comparison_n") or 0),
                "transactions a standing blocklist would flag")
            if aud.get("headline"):
                add("average_precision",
                    round(float(aud["headline"]["ap"]), 4),
                    "the mapped score column")
                add("roc_auc", round(float(aud["headline"]["roc_auc"]), 4),
                    "the mapped score column")
                pr = next(x for x in aud["budgets"] if x["primary"])
                add("reviews_per_day", int(pr["per_day"]),
                    "primary review budget")
                add("headline_recall_at_budget",
                    round(float(pr["headline_recall"]), 4),
                    "fraud transactions caught at the primary budget")
                add("first_hit_recall_at_budget",
                    round(float(pr["fs_recall"]), 4),
                    "fraud CASES caught at their first labelled "
                    "transaction")
                add("false_positives_at_budget",
                    int(pr["false_positives"]),
                    "good customers flagged at the primary budget")
                add("blocklist_coverable_share_of_hits",
                    round(float(pr["blocklist_coverable_rate"]), 4),
                    "correct alerts a standing blocklist would also "
                    "have covered")
        contract = {
            "contract_version": ev.CONTRACT_VERSION, "evidence_hash": "",
            "command": "chat", "transaction_id": None, "case_id": None,
            "decision": None, "lane": None, "fraud_probability": None,
            "episode_state": "n/a (dataset overview)",
            "evidence": items, "policy": None,
        }
        contract["evidence_hash"] = ev.canonical_hash(contract)
        return {k: contract[k] for k in ev.TOP_KEYS}

    def provider_chain(self, _p):
        from strikeone.ai import aiconfig
        cfg = aiconfig.AIConfig.load()
        if cfg is None:
            return {"text": "AI: disabled (the default). No provider "
                    "configured; every panel runs exactly as always.\n"
                    "Enable in your shell: strikeone ai setup"}
        return {"text": cfg.build().chain_text()}

    def route_curve(self, _p):
        self._need()
        res = run_route(self.df,
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
        if "score" not in self.df.columns:
            return self._raw_stream(p)          # no scorer: replay the flow
        if a["y"] is None:
            raise RuntimeError("stream needs labels")
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
                "id": str(a["tb"][i]),
                "day": round(float((a["t"][i] - a["day0"]) / 86400), 2),
                "amount": round(float(a["amt"][i]), 2),
                "entity": str(a["ent"][i]),
                "lane": "auto-block" if a["flag"][i] else "review",
                "caught_fs": bool(fs[i] and (alert[i] or a["flag"][i])),
                "role": int(a["roles"][i]),
            })
        return {"per_day": per_day, "n_events": int(len(events)),
                "rows": rows}

    def _raw_stream(self, p):
        """No score column: there are no decisions to replay, so we replay
        the raw transaction flow, marking labelled fraud. Honest fallback
        so the STREAM panel is never dead on score-less data."""
        a = self.arrays()
        order = np.argsort(a["t"], kind="stable")
        start, limit = int(p.get("start", 0)), int(p.get("limit", 400))
        rows = []
        for i in order[start:start + limit]:
            rows.append({
                "id": str(a["tb"][i]),
                "day": round(float((a["t"][i] - a["day0"]) / 86400), 2),
                "amount": round(float(a["amt"][i]), 2),
                "entity": str(a["ent"][i]),
                "lane": "review",
                "caught_fs": bool(a["y"] is not None
                                  and a["roles"][i] == episodes.ROLE_FIRST_STRIKE),
                "role": int(a["roles"][i]) if a["y"] is not None else 0,
            })
        return {"per_day": None, "n_events": int(len(a["t"])),
                "rows": rows, "raw": True}

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
                good = good[~good.index.astype(str)
                            .str.contains(r"(?:^|_)nan(?:_|$)", regex=True)]
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
        rows = [{"id": str(a["tb"][i]),
                 "day": round(float((a["t"][i] - a["day0"]) / 86400), 2),
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
               "ai": sess.ai, "evidence": sess.evidence,
               "provider_chain": sess.provider_chain,
               "onboard_scan": sess.onboard_scan,
               "onboard_validate": sess.onboard_validate,
               "onboard_accept": sess.onboard_accept,
               "onboard_skip": sess.onboard_skip,
               "onboard_finish": sess.onboard_finish,
               "onboard_abort": sess.onboard_abort,
               "ai_setup": sess.ai_setup,
               "chat": sess.chat,
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
        from strikeone.contract import json_safe
        sys.stdout.write(json.dumps(json_safe(out), default=float) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
