#!/usr/bin/env python3
"""test_loop.py — the bounded-autonomous-loop safety harness, as a real test module.

Every HALT path (GO / DRY / CAP / STOP-flag), the dry-reset on a real cross, and the
dry>=max satiety clamp, exercised on a throwaway state dir with a no-op snapshot
(hermetic — no git, no real ledger)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from antilarp.loop import Loop, selftest  # noqa: E402


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lp = Loop(Path(self.tmp.name), snapshot_fn=lambda root, label="": "deadbeef")

    def tearDown(self):
        self.tmp.cleanup()

    def test_go_at_start(self):
        self.lp.start(max_cycles=3, dry=2)
        go, msg = self.lp.preflight()
        self.assertTrue(go)
        self.assertIn("GO", msg)

    def test_dry_halts(self):
        self.lp.start(max_cycles=3, dry=2)
        self.lp.tick(crossed=0, candidates=1)
        self.lp.tick(crossed=0, candidates=0)
        go, msg = self.lp.preflight()
        self.assertFalse(go)
        self.assertIn("DRY", msg)

    def test_cap_halts(self):
        self.lp.start(max_cycles=3, dry=2)
        st = self.lp.load(); st["cycle"] = 3; self.lp.save(st)
        go, msg = self.lp.preflight()
        self.assertFalse(go)
        self.assertIn("MAX_CYCLES", msg)

    def test_stop_flag_halts(self):
        # the STOP flag halts the loop even when state still reads "running" — write the
        # file directly (raise_stop also flips status, which would short-circuit preflight
        # on the no-running-loop check before it reaches the STOP test).
        self.lp.start(max_cycles=3, dry=2)
        self.lp.stop.write_text("x")
        go, msg = self.lp.preflight()
        self.assertFalse(go)
        self.assertIn("STOP", msg)

    def test_raise_stop_sets_status_and_writes_flag(self):
        self.lp.start(max_cycles=3, dry=2)
        self.lp.raise_stop("manual")
        self.assertTrue(self.lp.stop.exists())
        self.assertEqual(self.lp.load()["status"], "halted-stop")
        go, _ = self.lp.preflight()
        self.assertFalse(go)

    def test_real_cross_resets_dry(self):
        self.lp.start(max_cycles=3, dry=2)
        self.lp.tick(crossed=0, candidates=1)
        self.assertEqual(self.lp.load()["consecutive_dry"], 1)
        self.lp.tick(crossed=1, candidates=2)
        self.assertEqual(self.lp.load()["consecutive_dry"], 0)

    def test_dry_ge_max_clamps_so_satiety_can_fire(self):
        self.lp.start(max_cycles=40, dry=99)
        self.assertLess(self.lp.load()["dry_threshold"], 40)

    def test_snapshot_is_recorded(self):
        self.lp.start(max_cycles=3, dry=2)
        snap = self.lp.snapshot("before-cross")
        self.assertEqual(snap, "deadbeef")
        self.assertEqual(self.lp.load()["snapshots"][-1]["sha"], "deadbeef")

    def test_selftest_passes(self):
        self.assertTrue(selftest())


if __name__ == "__main__":
    _runner = unittest.TextTestRunner(verbosity=1)
    _suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    _result = _runner.run(_suite)
    print(f"test_loop: {'PASS' if _result.wasSuccessful() else 'FAIL'} — {_result.testsRun} invariants")
    sys.exit(0 if _result.wasSuccessful() else 1)
