#!/usr/bin/env python3
"""cli.py — the command line for the anti-LARP limit ledger.

    python -m antilarp probe --transcripts <dir>
    python -m antilarp add --limit "..." --domain capability --class tooling [--note "..."]
    python -m antilarp cross <id> --crossing "..." --proof "..." [--joint]
    python -m antilarp cross <id> --crossing "..." --proof "..." \
        --load-bearing --critic-by gpt --critic-verdict confirm --critic-note "re-ran it"
    python -m antilarp park <id> --why "..."
    python -m antilarp hard <id> --why "..."
    python -m antilarp note <id> --text "..."
    python -m antilarp list [--json]
    python -m antilarp query [--status …] [--domain …] [--class …] [--count] [--json]
    python -m antilarp replay examples/sample-ledger.jsonl

Flags ``--ledger`` (default ./anti-larp-ledger.jsonl), ``--root`` (confinement dir,
default the ledger's directory), and ``--policy module:NAME`` (default the worked
example) make the repo independent of any directory layout or persona.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import ledger as L
from .policies.agent_self_improvement import POLICY as DEFAULT_EXAMPLE_POLICY
from .policy import LimitPolicy


def load_policy(spec: str | None) -> LimitPolicy:
    """Resolve ``--policy module:NAME`` to a LimitPolicy. None -> the worked example."""
    if not spec:
        return DEFAULT_EXAMPLE_POLICY
    mod_name, _, attr = spec.partition(":")
    attr = attr or "POLICY"
    mod = importlib.import_module(mod_name)
    pol = getattr(mod, attr)
    if not isinstance(pol, LimitPolicy):
        raise SystemExit(f"--policy {spec}: {attr} is not a LimitPolicy")
    return pol


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="antilarp",
                                 description="the anti-LARP limit ledger — find a limit, cross it, prove it, bank it")
    ap.add_argument("--ledger", default="anti-larp-ledger.jsonl", help="ledger file (default ./anti-larp-ledger.jsonl)")
    ap.add_argument("--root", default=None, help="confinement root (default: the ledger's directory)")
    ap.add_argument("--policy", default=None, help="module:NAME of a LimitPolicy (default: the worked example)")
    sub = ap.add_subparsers(dest="cmd")

    pr = sub.add_parser("probe", help="find a limit (scan a transcript/text dir, or name one)")
    pr.add_argument("--limit", help="name a limit directly (skips the scan)")
    pr.add_argument("--transcripts", help="directory of .jsonl transcripts to scan")
    pr.add_argument("--corpus", help="directory of .md/.txt files to scan")
    pr.add_argument("--top", type=int, default=8)

    ad = sub.add_parser("add", help="record a newly-found limit")
    ad.add_argument("--limit", required=True)
    ad.add_argument("--domain", required=True)
    ad.add_argument("--class", dest="klass", required=True)
    ad.add_argument("--note")

    cr = sub.add_parser("cross", help="cross a limit (with proof)")
    cr.add_argument("id")
    cr.add_argument("--crossing", required=True, help="the move that crossed it")
    cr.add_argument("--proof", required=True, help="before/after evidence + any decorrelated check")
    cr.add_argument("--joint", action="store_true", help="a human co-signed (required for a joint-required domain)")
    cr.add_argument("--load-bearing", dest="load_bearing", action="store_true",
                    help="a consequential crossing: requires a decorrelated critic-confirm")
    cr.add_argument("--critic-by", dest="critic_by", help="the decorrelated mind that reviewed it (a non-self, named party)")
    cr.add_argument("--critic-verdict", dest="critic_verdict", choices=("confirm", "refute", "unsure"),
                    help="the critic's verdict; a load-bearing crossing needs 'confirm'")
    cr.add_argument("--critic-note", dest="critic_note", help="one line: what the critic checked")

    pk = sub.add_parser("park", help="deliberately not crossing now (honest, not hidden)")
    pk.add_argument("id"); pk.add_argument("--why", required=True)

    hd = sub.add_parser("hard", help="mark the hard terminal — the honest wall")
    hd.add_argument("id"); hd.add_argument("--why", required=True)

    nt = sub.add_parser("note", help="annotate a limit (journal note; status unchanged)")
    nt.add_argument("id"); nt.add_argument("--text", required=True)

    ls = sub.add_parser("list", help="the ledger, folded to current state")
    ls.add_argument("--json", action="store_true")

    qy = sub.add_parser("query", help="slice the ledger by status/domain/class, with counts")
    qy.add_argument("--status"); qy.add_argument("--domain"); qy.add_argument("--class", dest="klass")
    qy.add_argument("--count", action="store_true"); qy.add_argument("--json", action="store_true")

    rp = sub.add_parser("replay", help="load a ledger file through the REAL validator and print folded state")
    rp.add_argument("file", help="a JSONL ledger to fold and render")

    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    policy = load_policy(args.policy)

    if args.cmd == "replay":
        path = Path(args.file).resolve()   # absolute, so confinement under root doesn't double-nest a relative path
        root = path.parent
        events = L.load_events(path, root)
        # re-validate every event through the REAL firewall so a stranger sees the gate work
        seen: list[dict] = []
        refused = []
        for ev in events:
            reason = L.validate(seen, ev, policy)
            if reason:
                refused.append((ev.get("id"), ev.get("status"), reason))
            else:
                seen.append(ev)
        print(L.render(seen, policy))
        if refused:
            print("\n  REFUSED by the firewall on replay:")
            for lid, st, reason in refused:
                print(f"    {lid} ({st}): {reason}")
        return 0

    ledger = Path(args.ledger).resolve()  # absolute so the relative default isn't re-nested under root
    root = Path(args.root).resolve() if args.root else ledger.parent

    def commit(ev):
        try:
            return L.append_event(ev, ledger, root, policy), None
        except ValueError as e:
            return None, str(e)

    if args.cmd == "probe":
        from . import probe as P
        if args.limit:
            print(f"  candidate limit:  {args.limit}")
            print(f"  suggested class:  {P.class_hint(args.limit)}   (a nudge — yours to set)")
            print(f"  next:  antilarp add --limit \"{args.limit}\" --domain <…> --class <…>")
            return 0
        if args.corpus:
            cands, ok, msg = P.scan_text_corpus(args.corpus, top=args.top)
        elif args.transcripts:
            cands, ok, msg = P.scan_jsonl_transcripts(args.transcripts, top=args.top)
        else:
            print("  name a limit with --limit, or point at --transcripts <dir> / --corpus <dir>.")
            return 0
        if msg:
            print(f"  {msg}")
        for c in cands:
            print(f"  x{c['count']:<2} {c['snippet']}   ({c['source']})")
        if cands:
            print("\n  these are CANDIDATES (signal, not authority — you judge which is a real wall).")
        return 0

    events = L.load_events(ledger, root)

    if args.cmd == "add":
        ev, err = commit(L.add_limit(events, args.limit, args.domain, args.klass, args.note))
        if err:
            print(f"  refused: {err}"); return 1
        print("  found:"); print(L._fmt(ev, policy)); return 0

    if args.cmd == "cross":
        critic = None
        if args.critic_by or args.critic_verdict or args.critic_note:
            critic = {"by": args.critic_by or "", "verdict": args.critic_verdict or "",
                      "note": args.critic_note or ""}
        ok, ev, msg = L.cross_limit(events, args.id, args.crossing, args.proof, args.joint,
                                    load_bearing=args.load_bearing, critic=critic, policy=policy)
        if not ok:
            print(f"  refused: {msg}"); return 1
        _, err = commit(ev)
        if err:
            print(f"  refused: {err}"); return 1
        print(f"  {msg}"); print(L._fmt(ev, policy)); return 0

    if args.cmd in ("park", "hard"):
        status = "parked" if args.cmd == "park" else policy.hard_status
        ok, ev, msg = L._restatus(events, args.id, status, args.why, policy=policy)
        if not ok:
            print(f"  refused: {msg}"); return 1
        _, err = commit(ev)
        if err:
            print(f"  refused: {err}"); return 1
        print(f"  {msg}"); print(L._fmt(ev, policy)); return 0

    if args.cmd == "note":
        ok, ev, msg = L.note_limit(events, args.id, args.text, policy=policy)
        if not ok:
            print(f"  refused: {msg}"); return 1
        _, err = commit(ev)
        if err:
            print(f"  refused: {err}"); return 1
        print(f"  {msg}"); print(L._fmt(ev, policy)); return 0

    if args.cmd == "query":
        matched = L.query_ledger(events, args.status, args.domain, args.klass)
        if args.count:
            print(len(matched)); return 0
        if getattr(args, "json", False):
            print(json.dumps(matched, ensure_ascii=False, indent=2)); return 0
        crit = ", ".join(c for c in (
            f"status={args.status}" if args.status else None,
            f"domain={args.domain}" if args.domain else None,
            f"class={args.klass}" if args.klass else None) if c) or "all"
        print(f"  query [{crit}] — {len(matched)} match(es) of {len(L.fold_events(events))} total")
        for e in matched:
            print(L._fmt(e, policy))
        return 0

    if args.cmd == "list" and getattr(args, "json", False):
        print(json.dumps(list(L.fold_events(events).values()), ensure_ascii=False, indent=2)); return 0

    print(L.render(events, policy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
