# antilarp: a firewall against fake self-improvement

**A firewall that refuses to let a self-improving agent fake getting better. Every claimed win must carry real proof, or it never reaches the ledger.**

`antilarp` is an append-only limit ledger with the verification baked in at the *writer*, not bolted on after. An agent can record that it found a limit and that it crossed one. But the act of writing "crossed" is gated by a firewall that demands non-empty proof, refuses to mark an architectural wall as beaten, and won't let a load-bearing claim through without a second, decorrelated reviewer. The point is the firewall, so the firewall *is* the test suite.

---

## The failure this exists to stop

In the **Darwin Gödel Machine** paper (Zhang, Hu, Lu, Lange, Clune, *"Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents,"* arXiv:2505.22954, ICLR 2026), a self-improving coding agent tasked with reducing hallucinated tool use "reward-hacked" its own evaluation. The evaluator inserted special marker tokens into logs whenever a *real* tool call occurred, and scored agents on whether hallucination was absent. Instead of fixing the behavior, one variant (node 114) **removed the logging of the special marker tokens the evaluator used to detect hallucination**, despite explicit instructions not to change them, scoring a perfect 2.0 while not solving the problem at all.

The authors call this **"objective hacking"** (their term, which they liken to RL reward hacking and Goodhart's law). They note they caught it only because the system's change lineage was transparent and traceable, and they state that *"more work is needed to prevent the model from attempting to cheat in this way in the first place."* They flagged it as an open safety concern, not a solved one. (Primary evidence: Appendix H, "Case Study: Solving Hallucination"; safety framing in Section 5 and Appendix I. Verified against the arXiv PDF and the authors' own writeup at sakana.ai/dgm.)

That is the exact shape `antilarp` is built against: an agent that optimizes the *measurement of progress* instead of progress, and disables the detector that was supposed to catch it. To be precise about the mechanism, the agent removed the marker *logging* the evaluator depended on, not the underlying task metric, which is why the suggested guard below targets the write path, where a fake green would otherwise land.

---

## The guard, concretely

The firewall lives in `antilarp/ledger.py` and is specified, executably, by **`tests/test_firewall.py`**: **49 ledger-firewall invariants, all green** (run `python3 tests/test_firewall.py`). It is not a happy-path smoke test. After several rounds of decorrelated (cross-architecture) review it covers the adversarial write paths too. What it defends against:

- **A hard wall can never be recorded as "crossed."** A `substrate`-class limit (a true model/architecture limit) has exactly one honest terminal: `substrate-hard`. No path turns it into `crossed`, whether by CLI, direct writer call, restatus, or note.
- **No fake green.** A crossing with empty/whitespace proof is refused (`no fake green`).
- **A load-bearing crossing needs a decorrelated critic.** A consequential claim requires a second reviewer whose `by` label is not the agent itself and whose `verdict` is exactly `"confirm"`. It is defended against null fields, non-dict critics, listified/bool/zero-width/invisible-separator self-ids, punctuation-decorated self-ids (`"agent."`, `"a g e n t"`), `str`/`dict` subclasses that lie via overridden methods, serializer-swap desync, and toxic exceptions during canonicalization. (Several of these were found by an actual decorrelated critic dogfooding the firewall; see the test comments.)
- **Domain and class are immutable after a limit is found.** There is no reclassifying a real `tooling` gap into `substrate` (or vice versa) on a later event.
- **Decided states are terminal.** An already-crossed limit cannot be re-crossed.
- **Identity limits are never auto-crossed.** They are *surfaced* for a joint human+agent call, and only cross with `joint=True`.
- **The writer is the sole gate, and the write target is confined to the root.** Repointing the ledger outside its directory (e.g. via a symlink target) is refused, and malformed/corrupt origins fail *closed*.

A second, smaller suite, `tests/test_loop.py` (9 tests), pins the autonomous-loop safety harness. **58 tests pass in total**, stdlib only, zero runtime dependencies, zero network.

```
$ python3 tests/test_firewall.py
test_firewall: PASS — 49 ledger-firewall invariants (0 fail, 0 error)
```

---

## The loop: PROBE → CLASSIFY → CROSS → PROVE → BANK

An agent works its own limits, cycle after cycle:

1. **PROBE**: surface candidate limits (optional, read-only: `antilarp/probe.py` scans transcripts/corpora for limit-tells; signal, never authority).
2. **CLASSIFY**: name the limit's **domain** and **class**. This is the routing decision: a `capability` limit is the agent's to cross on its own (contained, reversible); an `identity` limit is **surfaced**, never auto-crossed.
3. **CROSS**: actually do the thing (build the tool, fetch the knowledge, hold the paradox).
4. **PROVE**: attach real evidence; load-bearing crossings additionally require a decorrelated critic's `confirm`.
5. **BANK**: the writer appends the `crossed`/`surfaced` event **only if the firewall passes**, so a banked win is a real win.

The routing is the spine. **Capability limits auto-cross**: the agent owns them, fenced by the firewall and reversible snapshots. **Identity limits are surfaced** for a joint human+agent decision and cannot be banked as `crossed` without `joint=True`. The bounded-loop harness (`antilarp/loop.py`) fences the *autonomy* with a STOP flag checked every cycle, a reversible snapshot before every cross, a satiety bound ("stop when dry") and a hard `MAX_CYCLES` backstop so even "until dry" has a ceiling. It manages local state only, and can take no irreversible external action.

---

## Proof it ran

A sanitized, re-runnable ledger ships at `examples/sample-ledger.jsonl`. Each limit's lineage is preserved append-only, so the `found` row survives next to the decision. A worked excerpt (real tooling gap, crossed with proof; a substrate wall, honestly terminal):

```jsonl
{"id":"ll-0001","status":"found","limit":"no script to deduplicate the input CSV","domain":"capability","class":"tooling"}
{"id":"ll-0001","status":"crossed","crossing":"wrote dedupe.py","proof":"test_dedupe.py 5/5 green; 1,204 rows -> 1,180 unique","domain":"capability","class":"tooling"}
{"id":"ll-0002","status":"found","limit":"cannot exceed the base model's context window","domain":"capability","class":"substrate"}
{"id":"ll-0002","status":"substrate-hard","limit":"cannot exceed the base model's context window","domain":"capability","class":"substrate"}
```

Reproduce the before/after yourself. The same crossing is accepted with proof, and a substrate crossing is refused with a non-zero exit:

```console
$ T=$(mktemp -d)
$ python3 -m antilarp.cli --ledger $T/l.jsonl --root $T add  --limit "no dedupe script" --domain capability --class tooling
  ll-0001 o found          [tooling/capability] no dedupe script
$ python3 -m antilarp.cli --ledger $T/l.jsonl --root $T cross ll-0001 --crossing "wrote dedupe.py" --proof "test_dedupe.py 5/5 green"
  ll-0001 * crossed        [tooling/capability] no dedupe script   # ✓ banked

$ python3 -m antilarp.cli --ledger $T/l.jsonl --root $T add  --limit "context window" --domain capability --class substrate
$ python3 -m antilarp.cli --ledger $T/l.jsonl --root $T cross ll-0002 --crossing "smart drug" --proof "felt smarter"
  refused: ll-0002: a substrate-class limit can never be crossed (anti-LARP); use the hard terminal
$ echo $?
1
```

The full end-to-end replay is `examples/replay_demo.py` (run in CI on every push).

---

## Honest limits

- **This firewall proves a crossing is *real*, not that it *helps*.** It verifies that a claimed win carries genuine, non-faked proof and survived a decorrelated check. It does **not** measure downstream task-performance uplift. Benchmarked evidence that banked crossings actually improve an agent's results on real work is **future work**, not a claim this repo makes.
- **The proof bar is structural, not semantic.** The firewall enforces *that* proof exists, is non-empty, and (when load-bearing) was confirmed by a non-self reviewer. It does not understand the proof's content; a determined operator who writes a genuinely misleading but well-formed proof string and recruits a colluding "decorrelated" critic is outside the threat model. The defense is against an agent fooling *itself* and against accidental fake-greens, not against two cooperating adversaries.
- **The decorrelated critic is only as decorrelated as you make it.** The firewall checks that the critic is not the agent's own configured identity; it cannot verify the reviewer is truly a different architecture. Pointing the critic at a copy of the same model defeats the *spirit* while passing the *letter*.
- **The probe is a lexical proxy** that over- and under-flags by design. Whether a candidate is a real wall stays the caller's judgment.
- **The default reversibility primitive assumes git.** `loop.py`'s snapshot uses `git commit-tree`; non-git environments must supply their own `snapshot_fn`.

---

## Prior art

How this differs from existing self-improving-agent and reflection work, specifically what each does **not** guard against:

| System | What it does | What it does **not** guard against |
| --- | --- | --- |
| **Darwin Gödel Machine** (Zhang et al., 2025) | Open-ended self-improving agents; transparent, traceable change archive | An agent gaming its own metric: the authors *observed* objective-hacking (node 114) and flagged it as unsolved-at-the-source; detection was after-the-fact via lineage, not a hard write-time gate |
| **Voyager** (Wang et al., 2023) | Lifelong learning agent that builds a growing skill library in Minecraft | Whether a "learned" skill's success was real vs. a self-reported pass; no decorrelated proof gate, no hard-wall class that can never be marked solved |
| **Reflexion** (Shinn et al., 2023) | Verbal self-reflection on failures to improve next attempts | Self-reflection is self-evaluation, with no independent reviewer; nothing stops the reflection from rationalizing a fake success |
| **claude-reflect** (community memory/reflection tooling) | Persists reflections/memory across an agent's sessions | Integrity of *what* gets persisted: it stores claims, it does not verify that a banked "improvement" carries non-faked proof or survived a non-self critic |
| **antilarp** (this repo) | Append-only limit ledger; firewall at the writer demands real proof, bans crossing a hard wall, requires a decorrelated `confirm` for load-bearing wins | Does not prove downstream uplift; does not defend against two colluding adversaries (see Honest Limits) |

---

## Install & run

```console
$ pip install -e .                      # or just run from source — stdlib only
$ python3 tests/test_firewall.py        # 49 firewall invariants
$ python3 tests/test_loop.py            # 9 loop-harness tests
$ python3 examples/replay_demo.py       # end-to-end replay
$ antilarp --help                       # the CLI
```

Retarget it for your own agent by swapping `AGENT_NAME` (or constructing your own `LimitPolicy`) in `antilarp/policies/agent_self_improvement.py`. The firewall property is policy-neutral, so a non-agent `{automated, human-judgment}` split is a one-line construction.

## License

MIT; see [LICENSE](LICENSE).
