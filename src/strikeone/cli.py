"""The strikeone command line.

  strikeone check   validate a dataset against the input contract
  strikeone audit   the corrected evaluation, on your labelled data
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

from strikeone import audit as audit_mod
from strikeone import config, contract, examples
from strikeone import policy_engine
from strikeone import route as route_mod


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
    res = audit_mod.audit(df, label_delay_days=m.label_delay_days,
                          capacity_per_day=args.capacity)
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    print(res.to_json() if args.json
          else res.to_text(color=color, verbose=args.verbose))
    if args.example == "synthetic" and not args.json:
        print("\n(synthetic demonstration data; run against your own file "
              "with --map, or the frozen IEEE-CIS worked example)")
    if args.example == "ieee-cis" and not args.json:
        print("\nnote: this file is audited as a standalone window, exactly "
              "as your export\nwould be. The frozen stage reports evaluate "
              "the same window with the full\n182-day stream behind it, so "
              "episode counts differ (1,198 there vs the\nwithin-window "
              "count here), legitimately.")
    return 0


def cmd_route(args) -> int:
    df, m = _load(args)
    bl = None
    if args.blocklist:
        bl = set(Path(args.blocklist).read_text().split())
    res = route_mod.route(df, label_delay_days=m.label_delay_days,
                          blocklist_entities=bl)
    print(res.to_json() if args.json else res.to_text())
    if args.out:
        res.decisions.to_csv(args.out, index=False)
        print(f"routed decisions written to {args.out}", file=sys.stderr)
    return 0


def cmd_policy(args) -> int:
    df, m = _load(args)
    params = {}
    for k in ("m", "a", "e", "c_h"):
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


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog="strikeone",
        description="Bring-your-own-scorer fraud routing and the corrected "
                    "(first-strike) evaluation. Your data never leaves the "
                    "machine.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn, doc in [
        ("check", cmd_check, "validate a dataset against the input contract"),
        ("audit", cmd_audit, "first-strike recall vs your headline metric, "
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
                           help="your review capacity, alerts/day (otherwise "
                                "inferred from your fraud volume)")
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
            p.add_argument("--out", help="write recommendations to CSV")

    p = sub.add_parser("tui", help="terminal UI (Ink; needs Node 18+)")
    p.add_argument("rest", nargs="*")
    p.set_defaults(fn=cmd_tui)

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
