"""The strikeone command line.

  strikeone check   validate a dataset against the input contract
  strikeone audit   the corrected (first-hit) evaluation, on your data
  strikeone route   wrap any scorer with the two-lane routing
  strikeone policy  cost-derived {approve, step-up, block} recommendations
  strikeone tui     the terminal UI (needs Node 18+; core never does)

Every command prints human-readable output; add --json to pipe. We ship
the method and the measurement; you bring the scorer. No data ever leaves
the machine: no telemetry, no network calls.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from strikeone.audit import audit as run_audit
from strikeone import config, contract, examples
from strikeone import policy_engine
from strikeone.route import route as run_route


def _add_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", nargs="?", help="parquet/CSV path or DB URL")
    p.add_argument("--example", choices=["synthetic", "ieee-cis"],
                   help="run a built-in worked example instead of a source")
    p.add_argument("--map", action="append", default=[], metavar="K=V",
                   help="column mapping, e.g. --map amount=txn_amt "
                        "--map entity=card_hash+bin (repeatable)")
    p.add_argument("--delay", type=float, default=None,
                   help="label availability delay in days (default 7)")
    p.add_argument("--query", help="SQL query, for a DB URL source")
    p.add_argument("--table", help="table name, for a DB URL source")
    p.add_argument("--config", default=contract.CONFIG_FILE,
                   help=f"mapping file (default {contract.CONFIG_FILE})")
    p.add_argument("--save-config", action="store_true",
                   help="persist this mapping to the config file")
    p.add_argument("--json", action="store_true", help="emit JSON")


def _load(args) -> tuple:
    """(normalized df, mapping). Examples bypass mapping flags."""
    if args.example:
        raw, m = examples.resolve(args.example)
        if args.delay is not None:
            m.label_delay_days = args.delay
        return contract.apply_mapping(raw, m), m
    if not args.source:
        raise contract.ContractError(
            "give a data source (parquet/CSV path or DB URL) or --example"
        )
    if args.map:
        m = contract.Mapping.from_args(args.map, args.delay, args.source)
    elif Path(args.config).exists():
        m = contract.Mapping.load(args.config)
        if args.delay is not None:
            m.label_delay_days = args.delay
    else:
        raise contract.ContractError(
            "no column mapping: pass --map pairs once (add --save-config to "
            f"persist them to {args.config}) e.g.\n"
            "  --map transaction_id=txn_id --map timestamp=created_at \\\n"
            "  --map amount=amount --map entity=card_hash --map label=is_fraud"
        )
    raw = contract.read_source(args.source, query=args.query, table=args.table)
    df = contract.apply_mapping(raw, m)
    if args.save_config:
        m.save(args.config)
        print(f"mapping saved to {args.config}", file=sys.stderr)
    return df, m


def cmd_check(args) -> int:
    df, m = _load(args)
    rep = contract.check(df, m, for_audit=True)
    if args.json:
        print(json.dumps(rep.__dict__, indent=2, default=str))
    else:
        print(rep.to_text())
    return 0 if rep.ok else 2


def cmd_audit(args) -> int:
    df, m = _load(args)
    rep = contract.check(df, m, for_audit=True)
    if not rep.ok:
        print(rep.to_text(), file=sys.stderr)
        return 2
    if len(df) > 300_000 and sys.stderr.isatty():
        print(f"auditing {len(df):,} rows; this can take ~10s ...",
              file=sys.stderr)
    hist = None
    if args.history:
        hp = Path(args.history)
        if hp.suffix in (".parquet", ".pq", ".csv"):
            hdf = contract.read_source(str(hp))
            col = "entity" if "entity" in hdf.columns else hdf.columns[0]
            hist = set(hdf[col].astype(str))
        else:
            hist = set(hp.read_text().split())
    res = run_audit(df, label_delay_days=m.label_delay_days,
                          capacity_per_day=args.capacity,
                          history_entities=hist)
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    print(res.to_json() if args.json
          else res.to_text(color=color, verbose=args.verbose))
    if args.example == "synthetic" and not args.json:
        print("\n(synthetic demonstration data; run against your own file "
              "with --map, or the frozen IEEE-CIS worked example)")
    if args.example == "ieee-cis" and not args.json:
        print("""
why these numbers differ from reports/stage7 (they should, and here is how):
  scorer: this audits the frozen lane-2 model A2 standalone; the stage-7
    headline AP 0.5319 is Baseline A, and its 698/1,198 counters are the
    two-lane SYSTEM (blocklist lane + A2), not a bare scorer
  window truncation: fraudsters already active before day 151 look like
    fresh first hits inside this file, inflating cases to 1,462 vs
    stage 7's full-stream 1,198 (and the blocklist to 566 flags at 73.0%
    vs 1,775 at 49.8%). Disclosed in the footer; --history removes it
  alerts: 100/day x the exact 31.9985-day span = 3,199 vs stage 7's 3,200
Your own export gets exactly this standalone treatment, which is why the
hero shows it.""")
    return 0


def cmd_route(args) -> int:
    df, m = _load(args)
    rep = contract.check(df, m, for_audit=True)
    if not rep.ok:
        print(rep.to_text(), file=sys.stderr)
        return 2
    bl = None
    if args.blocklist:
        bl = set(Path(args.blocklist).read_text().split())
    res = run_route(df, label_delay_days=m.label_delay_days,
                          blocklist_entities=bl)
    print(res.to_json() if args.json else res.to_text())
    if args.out:
        res.decisions.to_csv(args.out, index=False)
        print(f"routed decisions written to {args.out}", file=sys.stderr)
    return 0


def cmd_policy(args) -> int:
    df, m = _load(args)
    rep = contract.check(df, m, for_audit=False)
    if not rep.ok:
        print(rep.to_text(), file=sys.stderr)
        return 2
    params = {}
    for k in ("m", "a", "e", "c_h", "s"):
        v = getattr(args, k if k != "c_h" else "ch")
        if v is not None:
            params[k] = v
    res = policy_engine.policy(df, params)
    print(res.to_json() if args.json else res.to_text())
    if args.out:
        res.decisions.to_csv(args.out, index=False)
        print(f"recommendations written to {args.out}", file=sys.stderr)
    return 0


def cmd_tui(args) -> int:
    tui_dir = config.REPO_ROOT / "tui"
    if not tui_dir.exists():
        print("the TUI lives in the repo, not the PyPI package (the Python "
              "core you have is fully functional without it):\n"
              "  git clone https://github.com/Thebinary110/Strike-One\n"
              "  cd Strike-One/tui && npm install && npx tsc",
              file=sys.stderr)
        return 2
    node = shutil.which("node")
    if not node:
        print("the TUI needs Node 18+ (the Python core does not). "
              "Install Node, then: cd tui && npm install", file=sys.stderr)
        return 2
    if not (tui_dir / "node_modules").exists():
        print("first run: cd tui && npm install", file=sys.stderr)
        return 2
    env = dict(os.environ, STRIKEONE_PY=sys.executable,
               STRIKEONE_ROOT=str(config.REPO_ROOT))
    return subprocess.call([node, str(tui_dir / "dist" / "cli.js"),
                            *args.rest], env=env, cwd=str(tui_dir))


def cmd_onboard(args) -> int:
    """AI-assisted schema onboarding: propose, validate deterministically,
    ask only where ambiguity matters, write the same .strikeone.toml a
    human would have. label is ALWAYS human-confirmed."""
    from strikeone import onboard as ob

    raw = contract.read_source(args.source, query=args.query,
                               table=args.table)
    print(f"Scanning dataset... {len(raw):,} rows, "
          f"{len(raw.columns)} columns")
    profiles = ob.profile_frame(raw, share_samples=args.share_samples)

    proposals = ob.heuristic_proposals(profiles)
    model, dropped = "heuristic only (no AI provider configured)", []
    from strikeone.ai import aiconfig
    cfg = aiconfig.AIConfig.load(args.ai_config)
    if cfg is not None:
        provider = cfg.build()
        print("\nAI proposer enabled - the redacted schema profile "
              "(column names, dtypes,\nstatistics, value shapes"
              + (", RAW SAMPLES (--share-samples)" if args.share_samples
                 else " - no raw values")
              + ") goes to:")
        print(provider.chain_text())
        from strikeone.ai.providers import ProviderError
        try:
            ai_props, dropped, model = ob.llm_proposals(profiles, provider)
            proposals += ai_props
        except ProviderError as e:
            print(f"\nAI proposer unavailable ({e}); continuing with the "
                  "heuristic proposer alone.", file=sys.stderr)

    pinned = {}
    if args.map:
        m_pin = contract.Mapping.from_args(args.map, args.delay,
                                           args.source)
        pinned = m_pin.columns
    decisions = ob.decide(raw, proposals, pinned=pinned)

    print("\nPROPOSED MAPPINGS")
    pending = []
    for t, d in decisions.items():
        if d.status == "auto":
            src = "+".join(d.source) if isinstance(d.source, list)                 else d.source
            print(f"  {src:<22} -> {t:<15} {d.confidence:>4.0%}  "
                  "OK auto-accepted"
                  + ("  (explicit --map)" if d.method == "user" else ""))
        elif d.status == "ask":
            pending.append(t)
        elif t in ob.REQUIRED:
            pending.append(t)

    interactive = sys.stdin.isatty() and not args.non_interactive
    for t in pending:
        d = decisions[t]
        if not interactive:
            continue
        print(f"\n? {t}: " + (
            f"proposed {d.source!r} ({d.confidence:.0%}, {d.method})"
            if d.source else "no candidate found"))
        if d.reason:
            print(f"    reason: {d.reason}")
        for w in d.validation.get("soft", []):
            print(f"    warning: {w}")
        if d.competing:
            print("    also considered: "
                  + ", ".join(f"{c} ({v:.0%})" for c, v in d.competing))
        if t == "label":
            print("    (label is always confirmed by a human: a wrong "
                  "label corrupts every\n     downstream number, and no "
                  "statistical check can verify its meaning)")
        if t == "entity":
            ans = input("    entity column(s), comma-separated "
                        f"[{d.source or ''}]: ").strip()
            src = [c.strip() for c in ans.split(",")] if ans                 else ([d.source] if d.source else None)
        else:
            ans = input(f"    column for {t} [{d.source or 'skip'}]: "
                        ).strip()
            src = ans or d.source
        if not src or src == "skip":
            if t in ob.REQUIRED:
                print(f"strikeone: {t} is required; aborting without "
                      "writing anything.", file=sys.stderr)
                return 2
            decisions[t] = ob.Decision(target_field=t)
            continue
        _as_list = lambda v: v if isinstance(v, list) else [v]  # noqa: E731
        typed_override = _as_list(src) != _as_list(d.source)
        val = ob.validate_field(t, raw, src)
        if val["hard"]:
            print("    REJECTED by validation: " + "; ".join(val["hard"]),
                  file=sys.stderr)
            return 2
        if t == "score":
            lb = decisions.get("label")
            if lb is not None and lb.source is not None:
                leak = ob.score_leak_check(
                    raw, src if not isinstance(src, list) else src[0],
                    lb.source if not isinstance(lb.source, list)
                    else lb.source[0])
                if leak and leak not in val["soft"]:
                    val["soft"].append(leak)
        # a typed override gets the SAME safety information the sidecar
        # records, BEFORE final acceptance (black-box finding 2: warnings
        # were computed and filed but never shown for typed answers)
        if val["soft"] and typed_override:
            for w in val["soft"]:
                print(f"    warning: {w}")
            sname = "+".join(src) if isinstance(src, list) else src
            if input(f"    proceed with {sname!r} anyway? [y/N]: "
                     ).strip().lower() != "y":
                print("    declined; aborting without writing anything.",
                      file=sys.stderr)
                return 2
        d.source, d.status, d.method = (
            src, "confirmed", d.method if not typed_override else "user")
        d.validation = val

    missing = [t for t in ob.REQUIRED
               if decisions[t].status not in ("auto", "confirmed")]
    if missing:
        print(f"strikeone: required fields need a human: "
              f"{', '.join(missing)}. Re-run interactively, or pin them: "
              + " ".join(f"--map {t}=<col>" for t in missing),
              file=sys.stderr)
        return 2

    # label delay: ALWAYS a question, never an inference
    delay = args.delay
    if delay is None and "label" in [t for t, d in decisions.items()
                                     if d.source is not None
                                     and d.status in ("auto", "confirmed")]:
        if interactive:
            ans = input("\nHow many days until a fraud label becomes "
                        "known? [assume 7]: ").strip()
            delay = float(ans) if ans else 7.0
        else:
            print("strikeone: pass --delay <days>; label delay is an "
                  "assumption you must state, not one we infer.",
                  file=sys.stderr)
            return 2
    delay = 7.0 if delay is None else delay

    m = ob.decisions_to_mapping(decisions, delay, args.source)
    cfg_path = Path(args.config)
    if cfg_path.exists():
        if interactive:
            if input(f"\n{cfg_path} exists - overwrite? [y/N]: "
                     ).strip().lower() != "y":
                print("kept the existing mapping; nothing written.")
                return 0
        else:
            print(f"strikeone: {cfg_path} exists; refusing to overwrite "
                  "non-interactively.", file=sys.stderr)
            return 2
    rec = ob.audit_record(decisions, profiles, delay, model, dropped,
                          args.share_samples)
    rep = ob.final_gate(raw, m)
    if not rep.ok:
        print("\nfinal contract check REFUSED the accepted mapping; "
              "nothing written:", file=sys.stderr)
        print(rep.to_text(), file=sys.stderr)
        return 2
    m.save(args.config)
    Path(args.audit_out).write_text(json.dumps(rec, indent=2))
    n_auto = sum(1 for d in decisions.values() if d.status == "auto")
    n_conf = sum(1 for d in decisions.values() if d.status == "confirmed")
    print(f"\n{n_auto} mapping(s) auto-accepted, {n_conf} human-confirmed"
          f"\nmapping written to {args.config}; decision audit in "
          f"{args.audit_out}")
    print(f"next: strikeone audit {args.source}")
    return 0


def cmd_ai(args) -> int:
    """AI narration layer. Disabled by default; deterministic commands
    never import this. The model never chooses a tool: argparse is the
    intent parser and evidence.BUILDERS is the router."""
    from strikeone.ai import aiconfig, commands, evidence

    if args.ai_cmd == "setup":
        detected = aiconfig.detect_env()
        if detected:
            print("credential env vars detected (values never shown, never "
                  "stored): " + ", ".join(detected))
        else:
            print("no credential env vars detected (OPENAI_API_KEY / "
                  "OPENROUTER_API_KEY). For a remote provider, export one "
                  "first; strikeone never prompts for secrets.")
        if not args.provider:
            print("configure with, e.g.:\n"
                  "  strikeone ai setup --provider ollama --model qwen3:8b\n"
                  "  strikeone ai setup --provider openai-compatible \\\n"
                  "    --base-url https://openrouter.ai/api/v1 \\\n"
                  "    --model openai/gpt-4o-mini "
                  "--api-key-env OPENROUTER_API_KEY")
            return 0
        cfg = aiconfig.AIConfig(provider=args.provider, model=args.model or "",
                                base_url=args.base_url or "",
                                api_key_env=args.api_key_env
                                or "OPENAI_API_KEY",
                                think=args.think or "")
        cfg.save(args.ai_config)
        print(f"written to {args.ai_config} (no secrets: it stores the env "
              "var's name, not its value)")
        return 0

    cfg = aiconfig.AIConfig.load(args.ai_config)

    if args.ai_cmd == "provider":
        if cfg is None:
            print("AI: disabled (the default). No provider configured; "
                  "every deterministic command runs exactly as always.\n"
                  "Enable with: strikeone ai setup")
            return 0
        print(cfg.build().chain_text())
        return 0

    df, m = _load(args)
    if args.show_evidence:
        builder = evidence.BUILDERS[args.ai_cmd]
        kw = {"capacity_per_day": int(args.capacity)} \
            if args.ai_cmd == "compare" else {}
        print(json.dumps(builder(df, m, args.target, **kw), indent=2))
        return 0
    if cfg is None:
        print("strikeone ai: disabled by default and no provider is "
              "configured.\nRun `strikeone ai setup`, or use "
              "--show-evidence to print the deterministic evidence "
              "contract with no model at all.", file=sys.stderr)
        return 2
    from strikeone.ai.providers import ProviderError
    try:
        res = commands.run(args.ai_cmd, df, m, args.target, cfg.build(),
                           capacity_per_day=int(args.capacity))
    except ProviderError as e:
        print(f"\u2717 AI provider unavailable\n\n{e}\n\n"
              "Core Strike One functionality (audit / route / policy / "
              "check) remains available.", file=sys.stderr)
        return 2
    if args.json:
        v = res["validated"]
        print(json.dumps({
            "contract": res["contract"], "model": res["model"],
            "provider": res["provider"], "validity": res["validity"],
            "lines": v.lines, "dropped": v.dropped}, indent=2))
    else:
        title = {"why": "WHY THIS DECISION", "timeline": "CASE TIMELINE",
                 "compare": "TWO SYSTEMS, ONE TRANSACTION"}[args.ai_cmd]
        print(f"STRIKE ONE AI  {title}  "
              f"({args.ai_cmd} {args.target})")
        print("─" * 74)
        print(res["rendered"])
    return 0


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `tui` forwards everything (incl. --help) to the node app untouched
    if argv[:1] == ["tui"]:
        class _A:  # minimal shim
            rest = argv[1:]
        sys.exit(cmd_tui(_A))

    from strikeone import __version__
    ap = argparse.ArgumentParser(
        prog="strikeone",
        description="Bring-your-own-scorer fraud routing and the corrected "
                    "(first-hit) evaluation. Your data never leaves the "
                    "machine.",
    )
    ap.add_argument("--version", action="version",
                    version=f"strikeone {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn, doc in [
        ("check", cmd_check, "validate a dataset against the input contract"),
        ("audit", cmd_audit, "first-hit recall vs your headline metric, "
                             "redundancy, blocklist recovery"),
        ("route", cmd_route, "two-lane routing around any scorer, with "
                             "measured lift"),
        ("policy", cmd_policy, "cost-derived approve/step-up/block "
                               "recommendations"),
    ]:
        p = sub.add_parser(name, help=doc)
        _add_source_args(p)
        p.set_defaults(fn=fn)
        if name == "audit":
            p.add_argument("--capacity", type=float, default=None,
                           help="your review capacity, alerts/day (default: "
                                "a stated 100/day)")
            p.add_argument("--history",
                           help="file of entity ids flagged BEFORE this "
                                "window (one per line, or csv/parquet with "
                                "an entity column); tightens first-hit "
                                "counts from upper bound to measured")
            p.add_argument("--verbose", action="store_true",
                           help="add the technical block (episodes, friction "
                                "efficiency)")
        if name == "route":
            p.add_argument("--blocklist",
                           help="file of known-bad entity ids, one per line "
                                "(prospective mode)")
            p.add_argument("--out", help="write routed decisions to CSV")
        if name == "policy":
            p.add_argument("--m", type=float, help="margin lost on a wrongly "
                           "declined good order (0.05-0.25)")
            p.add_argument("--a", type=float, help="step-up abandonment rate "
                           "(0.05-0.20)")
            p.add_argument("--e", type=float, help="step-up efficacy "
                           "(0.60-0.95)")
            p.add_argument("--ch", type=float, help="chargeback handling "
                           "cost, amount units (15-60)")
            p.add_argument("--s", type=float,
                           help="liability shifted to the issuer on a "
                                "successful step-up authentication (0-1; "
                                "default 0 = the frozen policy). India "
                                "caveat: RBI mandates AFA domestically, so "
                                "shift dynamics differ; stated, not modelled")
            p.add_argument("--out", help="write recommendations to CSV")

    sub.add_parser("tui", help="terminal UI (Ink; needs Node 18+); "
                               "strikeone tui --help for keys and usage")

    pon = sub.add_parser(
        "onboard",
        help="propose a column mapping for an unfamiliar dataset "
             "(heuristic + optional AI), validate it deterministically, "
             "confirm where it matters (label: always), write "
             ".strikeone.toml")
    pon.add_argument("source", help="parquet/CSV path or DB URL")
    pon.add_argument("--map", action="append", default=[], metavar="K=V",
                     help="pin a mapping explicitly; outranks every "
                          "proposal")
    pon.add_argument("--delay", type=float, default=None,
                     help="days until fraud labels are known (always "
                          "asked, never inferred)")
    pon.add_argument("--query", help="SQL query, for a DB URL source")
    pon.add_argument("--table", help="table name, for a DB URL source")
    pon.add_argument("--config", default=contract.CONFIG_FILE,
                     help=f"where to write (default {contract.CONFIG_FILE})")
    pon.add_argument("--audit-out", default=".strikeone.onboarding.json",
                     help="decision audit sidecar path")
    pon.add_argument("--share-samples", action="store_true",
                     help="include raw sample values in the profile sent "
                          "to the AI proposer (default: redacted shapes "
                          "only)")
    pon.add_argument("--non-interactive", action="store_true",
                     help="accept only auto-accepts and explicit --map "
                          "pins; anything needing a human exits 2")
    pon.add_argument("--ai-config", default=".strikeone-ai.toml",
                     help="AI provider config (default .strikeone-ai.toml)")
    pon.set_defaults(fn=cmd_onboard)

    pai = sub.add_parser("ai", help="AI narration of already-made decisions "
                                    "(disabled by default; every claim is "
                                    "validated against engine evidence)")
    sai = pai.add_subparsers(dest="ai_cmd", required=True)
    for name, doc, needs_target in [
        ("why", "explain one already-made decision, with cited evidence",
         True),
        ("timeline", "narrate one case: quiet purchases, the first "
                     "labelled transaction, the covered run after it", True),
        ("compare", "the two systems on one transaction, and why they "
                    "diverged", True),
        ("provider", "show the provider chain and where evidence goes",
         False),
        ("setup", "detect credentials (env vars only) and write the AI "
                  "config; never prompts for a secret", False),
    ]:
        q = sai.add_parser(name, help=doc)
        q.set_defaults(fn=cmd_ai)
        q.add_argument("--ai-config", default=".strikeone-ai.toml",
                       help="AI config file (default .strikeone-ai.toml)")
        if needs_target:
            q.add_argument("target",
                           help="transaction id (why/compare) or "
                                "case/entity id (timeline)")
            _add_source_args(q)
            q.add_argument("--capacity", type=float, default=100,
                           help="reviews/day for the compare budget "
                                "(default: the stated 100)")
            q.add_argument("--show-evidence", action="store_true",
                           help="print the deterministic evidence contract "
                                "and exit (no model, no provider)")
        if name == "setup":
            q.add_argument("--provider",
                           choices=["ollama", "openai-compatible"])
            q.add_argument("--model")
            q.add_argument("--base-url")
            q.add_argument("--api-key-env",
                           help="NAME of the env var holding the key "
                                "(default OPENAI_API_KEY); the value is "
                                "never read at setup time, never stored")
            q.add_argument("--think", choices=["on", "off"],
                           help="ollama hybrid-reasoning models: off skips "
                                "the thinking pass (narration needs none)")

    args = ap.parse_args(argv)
    try:
        sys.exit(args.fn(args))
    except contract.ContractError as e:
        print(f"strikeone: {e}", file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        print(f"strikeone: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
