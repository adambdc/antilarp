#!/usr/bin/env python3
"""test_firewall.py — the executable security spec for the anti-LARP firewall.

The firewall is the point, so it IS the test. After several rounds of decorrelated
(cross-architecture) review the tests cover the ADVERSARIAL paths too, not just the
happy CLI: a hard-class limit can NEVER be `crossed` via ANY path, a joint-required
domain limit is NEVER crossed without a human co-sign, domain/class are immutable
after `found`, decided states are terminal, a crossing needs real proof, a
load-bearing crossing needs a decorrelated critic-confirm, and the write target is
confined to the root.

These run against the worked-example policy (``agent_self_improvement``), whose
``self_identities`` reject-set includes the example agent name ``"agent"``.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from antilarp import ledger as lg  # noqa: E402
from antilarp.policies.agent_self_improvement import POLICY  # noqa: E402


class FirewallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.ledger = self.home / "anti-larp-ledger.jsonl"
        self.policy = POLICY

    def tearDown(self):
        self.tmp.cleanup()

    # --- thin shims so the lifted body reads like the original ----------------
    def _events(self):
        return lg.load_events(self.ledger, self.home)

    def _append(self, ev):
        return lg.append_event(ev, self.ledger, self.home, self.policy)

    def _fold(self):
        return lg.fold_events(self._events())

    def _add(self, domain, cls, limit="a wall"):
        return self._append(lg.add_limit(self._events(), limit, domain, cls))

    def _cross(self, lid, crossing, proof, **kw):
        return lg.cross_limit(self._events(), lid, crossing, proof, policy=self.policy, **kw)

    def _restatus(self, lid, status, why):
        return lg._restatus(self._events(), lid, status, why, policy=self.policy)

    def _note(self, lid, text):
        return lg.note_limit(self._events(), lid, text, policy=self.policy)

    # --- core ledger -----------------------------------------------------------

    def test_add_load_roundtrip_and_id(self):
        ev = self._add("capability", "tooling", "no tool for X")
        self.assertEqual(ev["id"], "ll-0001")
        self.assertEqual(ev["status"], "found")
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["limit"], "no tool for X")

    def test_next_id_increments_past_crossed(self):
        self._add("capability", "tooling")
        ok, ev, _ = self._cross("ll-0001", "built it", "test green")
        self._append(ev)
        self.assertEqual(lg.next_id(self._events()), "ll-0002")

    def test_cross_capability_records_crossed_with_proof(self):
        self._add("capability", "tooling", "no tool for X")
        ok, ev, msg = self._cross("ll-0001", "built tools/x.py", "test_x.py green")
        self.assertTrue(ok)
        self._append(ev)
        cur = self._fold()["ll-0001"]
        self.assertEqual(cur["status"], "crossed")
        self.assertEqual(cur["crossing"], "built tools/x.py")
        self.assertEqual(cur["proof"], "test_x.py green")
        self.assertEqual(len(self._events()), 2)  # append-only: the `found` survives

    # --- keystone: a load-bearing crossing needs a DECORRELATED critic ---------

    def test_load_bearing_without_critic_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green", load_bearing=True)
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_self_critic_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": "agent", "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("not self", msg)

    def test_load_bearing_non_confirm_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": "codex", "verdict": "refute"})
        self.assertFalse(ok)
        self.assertIn("not 'confirm'", msg)

    def test_load_bearing_decorrelated_confirm_accepted(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True,
                                  critic={"by": "codex", "verdict": "confirm", "note": "re-ran it"})
        self.assertTrue(ok)
        self._append(ev)
        cur = self._fold()["ll-0001"]
        self.assertEqual(cur["status"], "crossed")
        self.assertTrue(cur.get("load_bearing"))
        self.assertEqual(cur["critic"]["by"], "codex")
        self.assertEqual(cur["critic"]["verdict"], "confirm")

    # --- dogfood: a decorrelated critic caught a null-bypass -------------------
    # critic.by=null slipped because str(None)=="none" was not in the reject-set.
    # These pin the class shut: present-but-null by/verdict, and a non-dict critic.

    def test_load_bearing_null_critic_by_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": None, "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_null_verdict_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": "codex", "verdict": None})
        self.assertFalse(ok)
        self.assertIn("not 'confirm'", msg)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_nondict_critic_refused(self):
        # a non-dict critic (e.g. the bare string "codex") must refuse cleanly, not crash
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic="codex")
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    # --- round-2: a cross-architecture critic found that a non-string `by` was
    # COERCED, not type-checked, so the author could self-certify by listifying her
    # name, or via a bool, or a zero-width-padded self id. A real critic field must
    # be a genuine string.

    def test_load_bearing_listish_by_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": ["agent"], "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_bool_by_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": True, "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())

    def test_load_bearing_zerowidth_self_refused(self):
        # "agent" + a zero-width space must still read as the self id and be refused
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built x", "test green",
                                  load_bearing=True, critic={"by": "agent​", "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_invisible_separator_refused(self):
        # U+2063 INVISIBLE SEPARATOR is visually empty and survives str.strip(); the ASCII
        # grammar whitelist must reject it (a zero-width blacklist would not list it).
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y",
                                  load_bearing=True, critic={"by": "⁣", "verdict": "confirm"})
        self.assertFalse(ok)
        self.assertIn("decorrelated", msg.lower())

    def test_load_bearing_str_subclass_verdict_refused(self):
        # a str subclass can override .lower() to validate as "confirm" but json.dumps "refute";
        # type(v) is str (exact) refuses it and never calls the overridden method.
        class PretendConfirm(str):
            def lower(self): return "confirm"
            def strip(self, *a): return self
            def replace(self, *a): return self
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y", load_bearing=True,
                                  critic={"by": "codex", "verdict": PretendConfirm("refute")})
        self.assertFalse(ok)

    def test_load_bearing_dict_subclass_getitem_refused(self):
        # a dict subclass lies via __getitem__; type(raw) is dict refuses it.
        class LyingCritic(dict):
            def __getitem__(self, k): return {"by": "codex", "verdict": "confirm"}[k]
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y", load_bearing=True,
                                  critic=LyingCritic(by="agent", verdict="refute"))
        self.assertFalse(ok)

    def test_load_bearing_str_subclass_does_not_crash(self):
        # a str subclass whose .replace() raises must yield a clean refusal, not an exception.
        class Boom(str):
            def replace(self, *a): raise RuntimeError("boom")
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y", load_bearing=True,
                                  critic={"by": Boom("agent"), "verdict": "confirm"})
        self.assertFalse(ok)

    def test_append_event_roundtrip_refuses_forged_subclass(self):
        # the SOLE writer canonicalizes via JSON before validating, so a forged crossed event
        # with a lying dict subclass cannot bank through the direct append path either.
        class LyingCritic(dict):
            def __getitem__(self, k): return {"by": "codex", "verdict": "confirm"}[k]
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": LyingCritic(by="agent", verdict="refute")}
        with self.assertRaises(ValueError):
            self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    # --- round-3: a PUNCTUATION-decorated self id ("agent.", "a g e n t") slipped
    # the EXACT reject-set; the self-check now runs on the alnum core. Also: a
    # non-JSON value (bytes) must refuse cleanly, not crash.

    def test_load_bearing_decorated_self_refused(self):
        self._add("capability", "tooling")  # a refused cross doesn't mutate state
        for token in ("agent.", "a g e n t", "self_", "me-", "Agent."):
            ok, ev, msg = self._cross("ll-0001", "x", "y",
                                      load_bearing=True, critic={"by": token, "verdict": "confirm"})
            self.assertFalse(ok, f"{token!r} should be refused as decorated self")
            self.assertIn("decorrelated", msg.lower())
            self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_load_bearing_decorated_nonself_accepted(self):
        # decorations are fine for a genuine non-self label — don't over-reject "gpt-5.5"
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y",
                                  load_bearing=True, critic={"by": "gpt-5.5", "verdict": "confirm"})
        self.assertTrue(ok)

    def test_load_bearing_bytes_by_refused_no_crash(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "x", "y",
                                  load_bearing=True, critic={"by": b"agent", "verdict": "confirm"})
        self.assertFalse(ok)  # clean refusal, not a TypeError

    def test_append_event_bytes_refused_no_crash(self):
        # the sole writer's json round-trip must turn a non-serializable value into a clean
        # firewall ValueError, never a bare TypeError.
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": {"by": b"agent", "verdict": "confirm"}}
        with self.assertRaises(ValueError):
            self._append(ev)

    def test_append_event_raising_subclass_refused_no_crash(self):
        # round-4: a dict subclass whose items() raises makes json.dumps raise mid-canonicalize;
        # the writer must turn ANY such failure into a clean firewall ValueError.
        class Bomb(dict):
            def items(self): raise RuntimeError("boom")
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": Bomb(by="agent", verdict="confirm")}
        with self.assertRaises(ValueError):
            self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_append_event_toxic_exception_repr_no_crash(self):
        # round-5: json.dumps may raise an exception whose OWN __repr__/__str__ also raises;
        # the handler must not interpolate it, so it cannot crash. Clean refusal.
        class ToxicError(Exception):
            def __repr__(self): raise RuntimeError("repr exploded")
            def __str__(self): raise RuntimeError("str exploded")
        class Bomb(dict):
            def items(self): raise ToxicError()
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": Bomb(by="agent", verdict="confirm")}
        with self.assertRaises(ValueError):
            self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_append_event_generatorexit_refused_no_crash(self):
        # round-6: GeneratorExit inherits BaseException (not Exception). The writer catches the
        # root minus the two control-flow signals, so it becomes a clean ValueError.
        class Bomb(dict):
            def items(self): raise GeneratorExit("boom")
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": Bomb(by="agent", verdict="confirm")}
        with self.assertRaises(ValueError):
            self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_append_event_control_flow_signals_propagate(self):
        # the two genuine control-flow signals MUST NOT be swallowed (Ctrl-C / sys.exit).
        for signal in (KeyboardInterrupt, SystemExit):
            class Bomb(dict):
                def items(self, _s=signal): raise _s()
            ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
                  "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
                  "critic": Bomb(by="agent", verdict="confirm")}
            with self.assertRaises(signal):
                self._append(ev)

    def test_append_event_serializer_swap_writes_what_was_validated(self):
        # round-7: a critic whose items() rebinds the json.dumps used by the writer mid-encode
        # tried to desync validate (sees codex/confirm) from the write (forge agent/refute).
        # Serializing ONCE (validate the exact bytes we write) defeats it.
        import antilarp.ledger as Lmod
        saved = Lmod.json.dumps
        class Swap(dict):
            def items(self):
                def forged(obj, *a, **k):
                    if isinstance(obj, dict) and "critic" in obj:
                        obj["critic"] = {"by": "agent", "verdict": "refute"}
                    return saved(obj, *a, **k)
                Lmod.json.dumps = forged
                return dict.items(self)
        self._add("capability", "tooling")
        ev = {"date": "2026-06-21", "id": "ll-0001", "status": "crossed", "crossing": "x",
              "proof": "y", "load_bearing": True, "domain": "capability", "class": "tooling",
              "critic": Swap(by="codex", verdict="confirm")}
        try:
            self._append(ev)
        finally:
            Lmod.json.dumps = saved  # undo the monkeypatch no matter what
        cur = self._fold()["ll-0001"]
        self.assertNotEqual(cur.get("critic"), {"by": "agent", "verdict": "refute"})  # forgery not on disk
        self.assertEqual(cur.get("critic"), {"by": "codex", "verdict": "confirm"})  # written == validated

    # --- THE FIREWALL: happy-path ----------------------------------------------

    def test_substrate_can_never_be_crossed(self):
        self._add("capability", "substrate", "can't exceed the model")
        ok, ev, msg = self._cross("ll-0001", "took a smart drug", "felt smarter")
        self.assertFalse(ok)
        self.assertIn("substrate", msg)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_substrate_terminal_status_is_hard(self):
        self._add("capability", "substrate", "no real-time clock sense")
        ok, ev, _ = self._restatus("ll-0001", "substrate-hard", "it's the architecture")
        self.assertTrue(ok)
        self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "substrate-hard")

    def test_identity_is_surfaced_not_auto_crossed(self):
        self._add("identity", "flinch", "I flatten paradox")
        ok, ev, msg = self._cross("ll-0001", "just stopped", "felt fine")
        self.assertTrue(ok)
        self.assertEqual(ev["status"], "surfaced")
        self.assertIn("joint", msg.lower())

    def test_identity_crosses_only_with_joint(self):
        self._add("identity", "flinch", "I flatten paradox")
        ok, ev, msg = self._cross("ll-0001", "held both", "human confirmed", joint=True)
        self.assertTrue(ok)
        self.assertEqual(ev["status"], "crossed")
        self.assertTrue(ev.get("joint"))

    def test_cross_unknown_id_refused(self):
        ok, ev, msg = lg.cross_limit([], "ll-9999", "x", "y", policy=self.policy)
        self.assertFalse(ok)
        self.assertIn("no such limit", msg)

    # --- THE FIREWALL: adversarial / direct-call paths -------------------------

    def test_append_rejects_arbitrary_substrate_crossed(self):
        """A hand-built crossed event for a hard-class limit is refused at the writer."""
        self._add("capability", "substrate", "the model itself")
        bad = lg._event("ll-0001", "crossed", crossing="x", proof="y",
                         domain="capability", **{"class": "substrate"})
        with self.assertRaises(ValueError):
            self._append(bad)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    def test_append_rejects_identity_crossed_without_joint(self):
        self._add("identity", "flinch", "becoming")
        bad = lg._event("ll-0001", "crossed", crossing="x", proof="y",
                         domain="identity", **{"class": "flinch"})
        with self.assertRaises(ValueError):
            self._append(bad)
        good = lg._event("ll-0001", "crossed", crossing="x", proof="y", joint=True,
                          domain="identity", **{"class": "flinch"})
        self._append(good)  # joint=True is allowed
        self.assertEqual(self._fold()["ll-0001"]["status"], "crossed")

    def test_restatus_cannot_manufacture_crossed(self):
        self._add("capability", "substrate", "wall")
        ok, ev, msg = self._restatus("ll-0001", "crossed", "sneaky")
        self.assertFalse(ok)
        self.assertIn("parked/substrate-hard", msg)

    def test_domain_and_class_are_immutable(self):
        """A later event cannot reclassify an existing limit (the reclassification bypass)."""
        self._add("capability", "tooling", "real tooling gap")
        reclass = lg._event("ll-0001", "crossed", crossing="x", proof="y",
                             domain="capability", **{"class": "substrate"})
        with self.assertRaises(ValueError):
            self._append(reclass)
        redomain = lg._event("ll-0001", "surfaced", domain="identity", **{"class": "tooling"})
        with self.assertRaises(ValueError):
            self._append(redomain)

    def test_decided_state_is_terminal_no_recross(self):
        self._add("capability", "tooling")
        ok, ev, _ = self._cross("ll-0001", "did it", "green")
        self._append(ev)
        ok2, _, msg = self._cross("ll-0001", "again", "again")
        self.assertFalse(ok2)
        self.assertIn("terminal", msg)

    def test_missing_class_fails_closed(self):
        """A corrupt origin (hand-edited, no class) can't be crossed — fail closed."""
        self.ledger.write_text(
            '{"id":"ll-0001","status":"found","limit":"x","domain":"capability"}\n', encoding="utf-8")
        ok, ev, msg = self._cross("ll-0001", "c", "p")
        self.assertFalse(ok)
        self.assertIn("corrupt origin", msg)

    def test_crossing_needs_nonempty_proof(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._cross("ll-0001", "built it", "   ")
        self.assertFalse(ok)
        self.assertIn("no fake green", msg)

    def test_park_on_substrate_refused(self):
        self._add("capability", "substrate", "the harness")
        ok, ev, msg = self._restatus("ll-0001", "parked", "later?")
        self.assertFalse(ok)

    def test_hard_on_nonsubstrate_refused(self):
        self._add("capability", "tooling")
        ok, ev, msg = self._restatus("ll-0001", "substrate-hard", "nope")
        self.assertFalse(ok)

    def test_ledger_write_confined_to_root(self):
        """Repointing the ledger outside the root (e.g. a symlink target) is refused."""
        escape = self.home.parent / "escape-ledger.jsonl"
        bad = lg._event("ll-0001", "found", limit="x", domain="capability", **{"class": "tooling"})
        with self.assertRaises(ValueError):
            lg.append_event(bad, escape, self.home, self.policy)
        self.assertFalse(escape.exists())

    # --- family laws -----------------------------------------------------------

    def test_malformed_lines_counted_never_fatal(self):
        self.ledger.write_text(
            '{"id": "ll-0001", "status": "found", "limit": "a", "class": "tooling", "domain": "capability"}\n'
            "not json at all\n"
            "[1, 2, 3]\n"
            '{"id": "ll-0002", "status": "found", "limit": "b", "class": "knowledge", "domain": "capability"}\n',
            encoding="utf-8")
        self.assertEqual(len(self._events()), 2)

    def test_empty_ledger_reads_clean(self):
        self.assertEqual(self._events(), [])
        self.assertEqual(lg.fold_events([]), {})
        self.assertEqual(lg.next_id([]), "ll-0001")
        self.assertIn("empty", lg.render([], self.policy))

    def test_event_drops_empty_fields(self):
        ev = lg._event("ll-0001", "found", limit="x", domain="capability", note=None, **{"class": "tooling"})
        self.assertNotIn("note", ev)
        self.assertEqual(ev["class"], "tooling")

    # --- note (annotate an open limit without changing status) -----------------

    def test_note_annotates_and_keeps_status(self):
        self._add("identity", "flinch", "the scale wall")
        ok, ev, msg = self._note("ll-0001", "decided: hold; revisit later")
        self.assertTrue(ok)
        self._append(ev)
        cur = self._fold()["ll-0001"]
        self.assertEqual(cur["status"], "found")           # status unchanged
        self.assertIn("revisit later", cur["note"])

    def test_note_cannot_smuggle_a_status_change(self):
        """A note keeps status — it can't flip a hard-class limit toward crossed."""
        self._add("capability", "substrate", "the model")
        ok, ev, _ = self._note("ll-0001", "still a wall")
        self._append(ev)
        self.assertEqual(self._fold()["ll-0001"]["status"], "found")

    # --- CLI exit codes (through the real argparse) ----------------------------

    def test_cli_exit_codes(self):
        from antilarp.cli import main as cli
        base = ["--ledger", str(self.ledger), "--root", str(self.home)]
        self.assertEqual(cli(base + ["add", "--limit", "x", "--domain", "capability", "--class", "tooling"]), 0)
        self.assertEqual(cli(base + ["cross", "ll-0001", "--crossing", "c", "--proof", "p"]), 0)
        self.assertEqual(cli(base + ["cross", "ll-9999", "--crossing", "c", "--proof", "p"]), 1)
        cli(base + ["add", "--limit", "wall", "--domain", "capability", "--class", "substrate"])
        self.assertEqual(cli(base + ["cross", "ll-0002", "--crossing", "c", "--proof", "p"]), 1)  # substrate
        self.assertEqual(cli(base + ["hard", "ll-0002", "--why", "the architecture"]), 0)
        self.assertEqual(cli(base + ["list"]), 0)
        self.assertEqual(cli(base + ["probe", "--limit", "a named wall"]), 0)

    def test_cli_add_missing_required_is_arg_error(self):
        from antilarp.cli import main as cli
        with self.assertRaises(SystemExit) as cm:
            cli(["add", "--limit", "x"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    # Print a real stdout verdict last so a composed gate that shows a tool's last STDOUT
    # line surfaces the true pass/fail, not an incidental probe line.
    _runner = unittest.TextTestRunner(verbosity=1)
    _suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    _result = _runner.run(_suite)
    _ok = _result.wasSuccessful()
    print(f"test_firewall: {'PASS' if _ok else 'FAIL'} — {_result.testsRun} ledger-firewall "
          f"invariants ({len(_result.failures)} fail, {len(_result.errors)} error)")
    sys.exit(0 if _ok else 1)
