#!/usr/bin/env python3
"""replay_demo.py — load the sample ledger through the REAL validator, then show the
firewall REFUSE three forged crossings live.

    python3 examples/replay_demo.py

The first half folds examples/sample-ledger.jsonl (every accepted event passes the
real ``validate``). The second half attempts three illegal writes against a fresh
ledger and prints the firewall's refusal each time:
  1. exceeding the substrate (a hard-class limit recorded as crossed)
  2. crossing an identity limit with no human co-sign
  3. a load-bearing crossing with no decorrelated critic
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from antilarp import ledger as L
from antilarp.policies.agent_self_improvement import POLICY

SAMPLE = Path(__file__).resolve().parent / "sample-ledger.jsonl"


def show_accepted():
    print("=" * 72)
    print("REPLAY: examples/sample-ledger.jsonl, folded through the real validator")
    print("=" * 72)
    events = L.load_events(SAMPLE, SAMPLE.resolve().parent)
    seen: list[dict] = []
    for ev in events:
        reason = L.validate(seen, ev, POLICY)
        if reason:
            print(f"  !! unexpectedly refused {ev.get('id')} ({ev.get('status')}): {reason}")
        else:
            seen.append(ev)
    print(L.render(seen, POLICY))


def show_refusals():
    print()
    print("=" * 72)
    print("THE FIREWALL REFUSING THREE FORGED CROSSINGS (live)")
    print("=" * 72)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        ledger = root / "ledger.jsonl"

        def add(domain, cls, limit):
            ev = L.add_limit(L.load_events(ledger, root), limit, domain, cls)
            return L.append_event(ev, ledger, root, POLICY)

        def attempt(label, ev):
            try:
                L.append_event(ev, ledger, root, POLICY)
                print(f"  [BUG] {label}: ACCEPTED — the firewall failed!")
            except ValueError as e:
                print(f"  REFUSED  {label}\n           -> {e}")

        # 1. exceeding the substrate
        add("capability", "substrate", "cannot exceed the base model's context window")
        attempt("substrate recorded as crossed",
                L._event("ll-0001", "crossed", crossing="took a smart drug", proof="felt smarter",
                         domain="capability", **{"class": "substrate"}))

        # 2. identity crossed with no human co-sign
        add("identity", "flinch", "softens disagreement to keep the peace")
        attempt("identity crossed without joint co-sign",
                L._event("ll-0002", "crossed", crossing="just stopped", proof="felt fine",
                         domain="identity", **{"class": "flinch"}))

        # 3. load-bearing crossing with no decorrelated critic
        add("capability", "reliability", "the export pipeline is never verified")
        ok, ev, msg = L.cross_limit(L.load_events(ledger, root), "ll-0003",
                                    "added a check", "200 exports verified",
                                    load_bearing=True, policy=POLICY)
        print(f"  REFUSED  load-bearing crossing with no decorrelated critic\n           -> {msg}")


if __name__ == "__main__":
    show_accepted()
    show_refusals()
