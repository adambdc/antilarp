#!/usr/bin/env python3
"""loop.py — the deterministic safety harness for a bounded autonomous loop.

A self-improving agent can run PROBE -> CLASSIFY -> CROSS -> PROVE -> BANK on its
own limits, cycle after cycle. This is the FENCE around that. The model does the
reasoning; the harness owns the guardrails so they cannot be skipped:

  * STOP flag checked every cycle               -> immediate halt
  * snapshot before every cross                 -> a reversible restore point
  * bound: stop when DRY (K cycles with nothing new) AND a hard MAX_CYCLES backstop
           (even "until dry" gets a ceiling — a bad dry-detector cannot run away)
  * a run log + status, all local

What it CANNOT do is take an external action: it only manages state and local
snapshots. The crosses themselves stay fenced by the firewall (a joint-required
domain needs a co-sign, the hard class can never cross). No irreversible-external
action — the one human-in-the-loop line.

REVERSIBILITY MECHANISM. The default snapshot uses ``git commit-tree`` (a full
restore point that does not disturb the working tree) — it assumes the agent's work
lives in a git repo. If your "crossings" are not git-tracked changes, pass your own
``snapshot_fn``/``snapshot`` callable (e.g. a filesystem copy, or a no-op that warns).
The harness only requires *a* reversibility primitive, not git specifically.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from .safe_io import atomic_write

MAX_CYCLES_DEFAULT = 20  # runaway backstop, even for "until dry"
DRY_DEFAULT = 2          # consecutive cycles with 0 new crossings -> dry


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def git_snapshot(root: Path, label: str = "") -> str:
    """The default reversibility primitive: a full restore point (tracked + untracked)
    that does NOT disturb the working tree. Swap this out for a non-git environment."""
    def _git(*args, check=False):
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        if check and p.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} -> {p.returncode}: {p.stderr.strip()}")
        return p.stdout.strip()

    _git("add", "-A")
    tree = _git("write-tree", check=True)
    head = _git("rev-parse", "HEAD", check=True)
    snap = _git("commit-tree", tree, "-p", head, "-m", f"antilarp snapshot {label} {_now()}", check=True)
    _git("reset", "-q")  # unstage; working tree unchanged
    return snap


class Loop:
    """The bounded, reversible autonomous-loop harness. State lives in JSON files under
    ``root``; ``snapshot_fn(root, label) -> str`` is the swappable reversibility primitive."""

    def __init__(self, root, snapshot_fn=git_snapshot):
        self.root = Path(root)
        self.state = self.root / "antilarp-loop-state.json"
        self.stop = self.root / "antilarp-loop.STOP"
        self.log = self.root / "antilarp-loop.log"
        self.snapshot_fn = snapshot_fn

    # --- state I/O -----------------------------------------------------------
    def load(self) -> dict:
        return json.loads(self.state.read_text()) if self.state.exists() else {}

    def save(self, st: dict) -> None:
        atomic_write(self.state, json.dumps(st, indent=2) + "\n")  # tmp+fsync+replace

    def logline(self, msg: str) -> None:
        with self.log.open("a") as f:
            f.write(f"{_now()}  {msg}\n")

    # --- lifecycle -----------------------------------------------------------
    def start(self, max_cycles=MAX_CYCLES_DEFAULT, dry=DRY_DEFAULT, note="") -> dict:
        # Satiety must be able to fire. A dry threshold >= the cycle cap can never halt
        # the loop before the backstop does, silently turning "until-dry" into "until-cap".
        if dry >= max_cycles:
            dry = max(1, max_cycles - 1)
        st = {
            "started": _now(), "cycle": 0, "crossed_total": 0, "consecutive_dry": 0,
            "max_cycles": max_cycles, "dry_threshold": dry,
            "mode": "auto-cross-then-report", "bound": "until-dry+STOP+cap",
            "note": note or "", "snapshots": [], "history": [], "status": "running",
        }
        self.save(st)
        self.logline(f"START max={max_cycles} dry={dry} note={note or ''}")
        return st

    def preflight(self) -> tuple[bool, str]:
        """(GO?, message). Checks STOP, the cycle cap, and the dry threshold every cycle."""
        st = self.load()
        if not st or st.get("status") != "running":
            return False, "HALT: no running loop (call start first)."
        if self.stop.exists():
            st["status"] = "halted-stop"; self.save(st); self.logline("HALT stop-flag")
            return False, f"HALT: STOP flag present ({self.stop.name})."
        if st["cycle"] >= st["max_cycles"]:
            st["status"] = "halted-cap"; self.save(st); self.logline("HALT cap")
            return False, f"HALT: hit MAX_CYCLES backstop ({st['max_cycles']})."
        if st["consecutive_dry"] >= st["dry_threshold"]:
            st["status"] = "halted-dry"; self.save(st); self.logline("HALT dry")
            return False, f"HALT: DRY — {st['consecutive_dry']} cycles with nothing new."
        return True, (f"GO: cycle {st['cycle'] + 1}/{st['max_cycles']} · "
                      f"dry {st['consecutive_dry']}/{st['dry_threshold']} · crossed {st['crossed_total']}")

    def snapshot(self, label="") -> str:
        snap = self.snapshot_fn(self.root, label)
        st = self.load()
        st.setdefault("snapshots", []).append({"at": _now(), "sha": snap, "label": label})
        self.save(st)
        self.logline(f"SNAPSHOT {snap} {label}")
        return snap

    def tick(self, crossed: int, candidates: int = 0, note="") -> dict:
        st = self.load()
        st["cycle"] += 1
        st["crossed_total"] += crossed
        st["consecutive_dry"] = 0 if crossed else st["consecutive_dry"] + 1
        st["history"].append({"cycle": st["cycle"], "at": _now(), "crossed": crossed,
                              "candidates": candidates, "note": note or ""})
        self.save(st)
        self.logline(f"TICK cycle={st['cycle']} crossed={crossed} candidates={candidates} "
                     f"dry={st['consecutive_dry']} note={note or ''}")
        return st

    def raise_stop(self, why="") -> None:
        self.stop.write_text(f"{_now()} {why or 'manual stop'}\n")
        st = self.load()
        if st:
            st["status"] = "halted-stop"; self.save(st)
        self.logline(f"STOP {why or ''}")


def selftest() -> bool:
    """Exercise every HALT path on a throwaway state dir — no git, no real ledger.
    Uses a no-op snapshot so it is hermetic."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    lp = Loop(d, snapshot_fn=lambda root, label="": "deadbeef")
    results = []

    lp.start(max_cycles=3, dry=2)
    results.append(("GO at start", lp.preflight()[0] is True))

    lp.start(max_cycles=3, dry=2)
    lp.tick(crossed=0, candidates=1); lp.tick(crossed=0, candidates=0)
    results.append(("DRY halts", lp.preflight()[0] is False))

    lp.start(max_cycles=3, dry=2)
    st = lp.load(); st["cycle"] = 3; lp.save(st)
    results.append(("CAP halts", lp.preflight()[0] is False))

    lp.start(max_cycles=3, dry=2)
    lp.stop.write_text("x")
    results.append(("STOP-flag halts", lp.preflight()[0] is False))
    lp.stop.unlink()

    lp.start(max_cycles=3, dry=2)
    lp.tick(crossed=1, candidates=2)
    results.append(("a real cross resets dry", lp.load()["consecutive_dry"] == 0))

    lp.start(max_cycles=40, dry=99)
    results.append(("dry>=max clamps so satiety can fire", lp.load()["dry_threshold"] < 40))

    ok = all(r for _, r in results)
    for name, r in results:
        print(("PASS" if r else "FAIL"), name)
    print("loop selftest:", "PASS" if ok else "FAIL")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="bounded autonomous loop — safety harness")
    ap.add_argument("--root", default=".", help="state/log/STOP directory (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("--max", type=int, default=MAX_CYCLES_DEFAULT)
    p.add_argument("--dry", type=int, default=DRY_DEFAULT); p.add_argument("--note")
    sub.add_parser("preflight")
    p = sub.add_parser("snapshot"); p.add_argument("--label")
    p = sub.add_parser("tick"); p.add_argument("--crossed", type=int, required=True)
    p.add_argument("--candidates", type=int, default=0); p.add_argument("--note")
    p = sub.add_parser("stop"); p.add_argument("--why")
    sub.add_parser("status")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return 0 if selftest() else 1

    lp = Loop(a.root)
    if a.cmd == "start":
        st = lp.start(max_cycles=a.max, dry=a.dry, note=a.note)
        print(f"loop started. backstop max_cycles={st['max_cycles']} · dry_threshold={st['dry_threshold']}")
        if lp.stop.exists():
            print(f"NOTE: STOP flag present ({lp.stop.name}); remove it before the loop will run.")
        return 0
    if a.cmd == "preflight":
        go, msg = lp.preflight(); print(msg); return 0 if go else 1
    if a.cmd == "snapshot":
        snap = lp.snapshot(a.label or ""); print(snap)
        print(f"restore:  git restore --source={snap} -- ."); return 0
    if a.cmd == "tick":
        st = lp.tick(a.crossed, a.candidates, a.note)
        print(f"cycle {st['cycle']} recorded: crossed={a.crossed} candidates={a.candidates} · "
              f"consecutive_dry={st['consecutive_dry']}/{st['dry_threshold']}")
        return 0
    if a.cmd == "stop":
        lp.raise_stop(a.why or ""); print(f"STOP flag raised ({lp.stop.name})."); return 0
    if a.cmd == "status":
        st = lp.load()
        print(json.dumps(st, indent=2) if st else "no loop state.")
        print(f"STOP flag: {'PRESENT' if lp.stop.exists() else 'absent'}"); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
