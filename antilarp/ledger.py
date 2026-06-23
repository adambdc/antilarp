#!/usr/bin/env python3
"""ledger.py — the anti-LARP firewall + the append-only limit ledger.

A self-improving agent keeps an append-only ledger of its own limits and crosses
them. The firewall makes it structurally impossible to record a fake win:

THE FIREWALL — one validator (``validate``) that EVERY write passes through, so it
binds direct function calls and the CLI alike (not just the happy path). It is
mechanized in ``tests/test_firewall.py``, not asserted in prose:

  - a ``hard_class`` limit (a true hard model/architecture limit) can NEVER be
    marked ``crossed``. Its only terminal is ``substrate-hard``. The anti-LARP
    clause: no code path can record exceeding the substrate, so it cannot tell that
    lie to a future run.
  - a ``joint_required`` domain limit can NEVER be auto-crossed; without an explicit
    human co-sign (``joint=True``) a cross is recorded ``surfaced``, not ``crossed``.
  - domain & class are IMMUTABLE after ``found`` (no reclassification bypass); decided
    states are terminal (no re-crossing); a crossing needs real ``crossing``+``proof``
    (no fake green); a LOAD-BEARING crossing needs a DECORRELATED critic-confirm
    (a model cannot reliably self-verify); the write target is confined to a root.

Append-only event log: each line is one event; the latest per id is current state.
The ledger is append-only *by convention* — it is NOT cryptographically tamper-
evident (a hand edit of the file is outside the tool; that residual is documented,
not hidden). Hardened across several rounds of cross-architecture (decorrelated)
review that found the happy-path-only gaps. Zero-dependency, restart-safe.

The vocabulary (domains / classes / statuses / the hard class / the joint-required
domains / the critic self-identity reject-set) all come from an injected
``LimitPolicy`` — the firewall LOGIC is fixed, only the names are configuration.
"""
from __future__ import annotations

import json
import re
from datetime import date as _date
from pathlib import Path

from .policy import DEFAULT_POLICY, LimitPolicy
from .safe_io import iter_jsonl_dicts, resolve_in_root, safe_read_text


# --- ledger I/O (append-only; latest event per id wins) -----------------------

def load_events(ledger: Path, root: Path) -> list[dict]:
    """All events, oldest first. A malformed line is skipped but WARNED: the ledger
    is load-bearing, so a corrupted entry must nag, not vanish."""
    return list(iter_jsonl_dicts(ledger, root, warn=True))


def fold_events(events: list[dict]) -> dict[str, dict]:
    """Collapse the event log to current state: latest event per id, first-seen order."""
    cur: dict[str, dict] = {}
    for e in events:
        lid = e.get("id")
        if isinstance(lid, str) and lid:
            cur[lid] = e  # re-assigning a key keeps its original position (py3.7+)
    return cur


def _origin(events: list[dict], lid: str) -> dict | None:
    """The FIRST event for an id — its ``found``. domain/class are fixed here, forever."""
    for e in events:
        if e.get("id") == lid:
            return e
    return None


def next_id(events: list[dict], prefix: str = "ll-") -> str:
    """``<prefix>NNNN``, one past the highest numeric id ever seen (crossed events reuse ids)."""
    mx = 0
    for e in events:
        lid = e.get("id", "")
        if isinstance(lid, str) and lid.startswith(prefix):
            try:
                mx = max(mx, int(lid[len(prefix):]))
            except ValueError:
                pass
    return f"{prefix}{mx + 1:04d}"


def _event(lid: str, status: str, today: str | None = None, **fields) -> dict:
    """Build one event. Empty/None fields are dropped (honest absence, not null spam)."""
    ev = {"date": today or _date.today().isoformat(), "id": lid, "status": status}
    for k, v in fields.items():
        if v not in (None, "", False):
            ev[k] = v.strip() if isinstance(v, str) else v
    return ev


# --- THE FIREWALL: one validator every write obeys ----------------------------

# A critic provenance/verdict is an EXACT str matching a strict ASCII grammar (a
# WHITELIST, not an invisible-char blacklist). Hardened after a cross-architecture
# critic review:
#   - type(v) is str, NOT isinstance — a str SUBCLASS can override .lower()/.strip()/
#     .replace() to validate as one value but json.dumps another (validate "confirm",
#     store "refute"), or raise.
#   - the ASCII grammar refuses U+2063 INVISIBLE SEPARATOR and the like (str.strip()
#     misses them) and homoglyphs — they fail the match and collapse to "" -> refused,
#     never an empty-equivalent id.
# (append_event additionally re-validates the JSON round-trip, so the firewall judges
#  exactly the bytes that will be written — a dict subclass that lies via __getitem__
#  can't validate-vs-store split. A forged provenance label, or a raw hand-edit, remain
#  the author's to make — append-only by convention, not cryptographically tamper-proof.)
_CRITIC_GRAMMAR = re.compile(r"[a-z0-9][a-z0-9 ._-]*")


def _critic_field(v) -> str:
    if type(v) is not str:          # exact str only — a subclass can lie via overridden methods
        return ""
    s = v.strip().lower()
    return s if _CRITIC_GRAMMAR.fullmatch(s) else ""   # strict ASCII whitelist; invisibles -> ""


def validate(events: list[dict], ev: dict, policy: LimitPolicy = DEFAULT_POLICY) -> str | None:
    """None if appending ``ev`` is legal, else a reason string. EVERY write goes through
    here (via append_event), so the rules bind a direct call exactly as the CLI — the
    firewall is data-layer, not happy-path. Fail-closed: anything unrecognised refuses.

    All vocabulary is read from ``policy``; the LOGIC below is fixed."""
    lid, status = ev.get("id"), ev.get("status")
    if not isinstance(lid, str) or not lid:
        return "event has no id"
    if status not in policy.statuses:
        return f"unknown status: {status!r}"

    origin = _origin(events, lid)
    if origin is None:
        # a brand-new limit: must be a clean ``found`` with a valid domain + class
        if status != policy.found_status:
            return f"new limit {lid} must start as {policy.found_status!r}, not {status!r}"
        if ev.get("domain") not in policy.domains:
            return f"invalid domain: {ev.get('domain')!r}"
        if ev.get("class") not in policy.classes:
            return f"invalid class: {ev.get('class')!r}"
        return None

    # an existing limit — domain & class are immutable (set at ``found``); the
    # authoritative class/domain come from the origin, so a missing/forged field
    # on this event can't change the verdict.
    domain, cls = origin.get("domain"), origin.get("class")
    if cls not in policy.classes or domain not in policy.domains:
        return f"{lid}: corrupt origin (class={cls!r}, domain={domain!r}); refusing"
    if "domain" in ev and ev["domain"] != domain:
        return f"{lid}: domain is immutable ({domain}); refusing to reclassify"
    if "class" in ev and ev["class"] != cls:
        return f"{lid}: class is immutable ({cls}); refusing to reclassify"

    prev = (fold_events(events).get(lid) or {}).get("status", policy.found_status)
    if policy.is_terminal(prev):
        return f"{lid} is {prev} (terminal); no further transition"
    if status == prev:
        return None  # a same-status note/annotation on an OPEN limit — not a transition

    if status == "crossed":
        if cls == policy.hard_class:
            return (f"{lid}: a {policy.hard_class}-class limit can never be crossed "
                    f"(anti-LARP); use the hard terminal")
        if policy.requires_joint(domain) and not ev.get("joint"):
            return (f"{lid}: domain {domain!r} is not auto-crossed; surface it, or cross "
                    f"with joint=True (a human co-sign)")
        if not str(ev.get("crossing", "")).strip() or not str(ev.get("proof", "")).strip():
            return f"{lid}: a crossing needs non-empty crossing AND proof (no fake green)"
        # the keystone: a LOAD-BEARING crossing needs a DECORRELATED critic-confirm.
        # Non-empty proof is provably insufficient (a model cannot reliably self-verify);
        # only an independent mind closes the integrity->validity gap. Non-load-bearing
        # crossings unchanged.
        if ev.get("load_bearing"):
            # The critic object and its fields must be EXACT builtins (a str/dict subclass
            # can lie — see _critic_field and append_event's JSON round-trip). Non-dict
            # critic -> {} -> refused.
            raw = ev.get("critic")
            critic = raw if type(raw) is dict else {}     # EXACT dict — a subclass lies via __getitem__
            by = _critic_field(critic.get("by"))
            verdict = _critic_field(critic.get("verdict"))
            # the self-check runs on the ALNUM CORE, so a punctuation/space-decorated self
            # id ("agent.", "a g e n t", "self_", "me-") collapses to its core and is still
            # refused. verdict stays an EXACT "confirm" below. (A non-self-LOOKING forged
            # label — by="codex" with no real codex — is the conceded out-of-scope case: a
            # forged label, like a hand-edit, is the author's to make; the gate is a speed
            # bump, not a cryptographic attestation.)
            by_core = re.sub(r"[^a-z0-9]", "", by)
            if by_core in policy.self_identities:
                return (f"{lid}: a load-bearing crossing needs a DECORRELATED critic, not self "
                        f"— get a verdict from a second mind, then cross with "
                        f"--critic-by <a non-self, named second party> --critic-verdict confirm")
            if verdict != "confirm":
                return (f"{lid}: load-bearing critic verdict is {verdict or 'missing'!r}, not "
                        f"'confirm' — external verification gates the crossing; proof alone "
                        f"does not")
    elif status == policy.hard_status:
        if cls != policy.hard_class:
            return f"{lid}: only {policy.hard_class}-class goes {policy.hard_status} (this is {cls})"
    elif status == policy.surfaced_status:
        if not policy.requires_joint(domain):
            return f"{lid}: only a joint-required domain is surfaced (this is {domain})"
    elif status == "parked":
        if cls == policy.hard_class:
            return f"{lid}: a {policy.hard_class} limit isn't parked (not crossable); use the hard terminal"
    return None


def append_event(ev: dict, ledger: Path, root: Path,
                 policy: LimitPolicy = DEFAULT_POLICY) -> dict:
    """The SOLE writer. Confines the target to ``root``, then SERIALIZES ONCE: it validates
    the parse of the exact bytes it will write, and writes those same bytes. (Validating a
    re-serialization — a second json.dumps — would let a malicious object rebind json.dumps
    between validate and write, desyncing them. One serialization makes that impossible: we
    write exactly what we validated.) Raises ValueError on a refused write — so no DATA path,
    CLI or direct call, can bank an illegal event. (Arbitrary CODE the author runs in-process
    — monkeypatching stdlib, rebinding validate, writing the file directly — is out of scope:
    that is a hand-edit by another name, and the ledger is append-only by convention, not
    cryptographically tamper-proof against its author.)"""
    safe = resolve_in_root(ledger, root)
    if safe is None:
        raise ValueError(f"ledger path escapes root; refusing to write: {ledger}")
    try:
        line = json.dumps(ev, ensure_ascii=False)  # serialize ONCE -> the exact bytes we will write
        ev = json.loads(line)                      # validate the parse of THOSE bytes (plain builtins)
    except (KeyboardInterrupt, SystemExit):
        raise  # genuine control-flow signals propagate — never swallow Ctrl-C / sys.exit
    except BaseException:  # noqa: BLE001 — catch the ROOT minus the two signals above, so GeneratorExit
        # and any exotic BaseException an adversarial items() raises fail closed too. Reference the
        # caught object NOWHERE (its __repr__/__str__ may also raise): static message + `from None`.
        # The set that can still escape is now EXACTLY {KeyboardInterrupt, SystemExit} — both
        # intended — so the "exotic exception escapes" class is exhaustively closed.
        raise ValueError("firewall: event is not plain JSON — canonicalization failed "
                         "(unserializable value, or an object that raised during encoding)") from None
    reason = validate(load_events(ledger, root), ev, policy)
    if reason:
        raise ValueError(f"firewall: {reason}")
    with safe.open("a", encoding="utf-8") as f:
        f.write(line + "\n")  # the SAME bytes we validated — no second json.dumps to hijack
    return ev


# --- the actions (each builds an event; validate / append_event re-check) ------

def add_limit(events, limit, domain, cls, note=None, today=None, prefix="ll-"):
    """Record a newly-found limit (status ``found``). Returns the event (caller appends)."""
    return _event(next_id(events, prefix), "found", today, limit=limit, domain=domain,
                  note=note, **{"class": cls})


def cross_limit(events, lid, crossing, proof, joint=False, today=None,
                load_bearing=False, critic=None, policy: LimitPolicy = DEFAULT_POLICY):
    """Try to cross a limit. Returns (ok, event_or_None, message). The firewall lives in
    ``validate``; the hard class is refused, a joint-required domain without a co-sign
    becomes ``surfaced``, and a load-bearing crossing without a decorrelated critic-confirm
    is refused."""
    cur = fold_events(events).get(lid)
    if cur is None:
        return False, None, f"no such limit: {lid}"
    origin = _origin(events, lid) or cur
    base = {"limit": cur.get("limit", ""), "domain": origin.get("domain"),
            **{"class": origin.get("class")}}

    if policy.requires_joint(base["domain"]) and not joint:
        ev = _event(lid, policy.surfaced_status, today, crossing=crossing, proof=proof,
                    note="joint-required domain — surfaced for a human co-sign, not "
                         "auto-crossed; re-run with joint=True once decided together", **base)
        r = validate(events, ev, policy)
        if r:
            return False, None, r
        return True, ev, (
            f"{lid} is domain={base['domain']} — NOT auto-crossed. Recorded as SURFACED for a "
            f"joint decision. Re-run with joint=True once a human has co-signed.")

    ev = _event(lid, "crossed", today, crossing=crossing, proof=proof, joint=bool(joint),
                load_bearing=bool(load_bearing), critic=(critic or None), **base)
    r = validate(events, ev, policy)
    if r:
        return False, None, r
    tag = " (load-bearing, critic-confirmed)" if load_bearing else ""
    return True, ev, f"{lid} crossed.{tag}"


def _restatus(events, lid, status, why, today=None, policy: LimitPolicy = DEFAULT_POLICY):
    """park / hard only — never a back-door to ``crossed``. Carries the immutable
    limit/domain/class forward and lets ``validate`` have the final say."""
    if status not in ("parked", policy.hard_status):
        return False, None, f"_restatus sets only parked/{policy.hard_status}, not {status!r}"
    cur = fold_events(events).get(lid)
    if cur is None:
        return False, None, f"no such limit: {lid}"
    origin = _origin(events, lid) or cur
    ev = _event(lid, status, today, limit=cur.get("limit", ""), domain=origin.get("domain"),
                note=why, **{"class": origin.get("class")})
    r = validate(events, ev, policy)
    if r:
        return False, None, r
    return True, ev, f"{lid} -> {status}."


def note_limit(events, lid, text, today=None, policy: LimitPolicy = DEFAULT_POLICY):
    """Annotate a limit with a journal note WITHOUT changing its status — so an open
    limit's understanding can evolve. Appends to the existing note, preserving provenance."""
    cur = fold_events(events).get(lid)
    if cur is None:
        return False, None, f"no such limit: {lid}"
    origin = _origin(events, lid) or cur
    merged = "; ".join(p for p in [cur.get("note"), text.strip()] if p)
    ev = _event(lid, cur.get("status", policy.found_status), today, limit=cur.get("limit", ""),
                domain=origin.get("domain"), note=merged, crossing=cur.get("crossing"),
                proof=cur.get("proof"), joint=cur.get("joint"), **{"class": origin.get("class")})
    r = validate(events, ev, policy)
    if r:
        return False, None, r
    return True, ev, f"{lid} noted (status unchanged: {cur.get('status')})."


# --- rendering / query --------------------------------------------------------

def _fmt(e: dict, policy: LimitPolicy = DEFAULT_POLICY) -> str:
    icon = policy.icons.get(e.get("status"), ".")
    tag = f"[{e.get('class','?')}/{e.get('domain','?')}]"
    line = f"  {e.get('id','?')} {icon} {e.get('status','?'):<14} {tag} {e.get('limit','')}"
    for label, key in (("crossed", "crossing"), ("proof", "proof"), ("note", "note")):
        if e.get(key):
            line += f"\n            -> {label}: {e[key]}"
    if e.get("joint"):
        line += "\n            -> joint (human co-signed)"
    return line


def query_ledger(events: list[dict], status=None, domain=None, cls=None) -> list[dict]:
    """Slice the folded ledger by status/domain/class. domain & class come from the
    ORIGIN (immutable at ``found``) — the same authoritative source the firewall trusts,
    so the slice can't be fooled by a missing/forged field on a later event. Read-only."""
    out = []
    for lid, e in fold_events(events).items():
        origin = _origin(events, lid) or {}
        d = origin.get("domain", e.get("domain"))
        c = origin.get("class", e.get("class"))
        if status and e.get("status") != status:
            continue
        if domain and d != domain:
            continue
        if cls and c != cls:
            continue
        out.append(e)
    return out


def render(events: list[dict], policy: LimitPolicy = DEFAULT_POLICY) -> str:
    cur = fold_events(events)
    if not cur:
        return "  ledger is empty — no limits found yet."
    vals = list(cur.values())
    n = len(vals)
    crossed = sum(1 for e in vals if e.get("status") == "crossed")
    hard = sum(1 for e in vals if e.get("status") == policy.hard_status)
    surfaced = sum(1 for e in vals if e.get("status") == policy.surfaced_status)
    openc = sum(1 for e in vals if e.get("status") == policy.found_status)
    parked = sum(1 for e in vals if e.get("status") == "parked")
    head = (f"  limit ledger — {n} limit(s): {crossed} crossed - {openc} open - "
            f"{surfaced} surfaced - {hard} {policy.hard_status} - {parked} parked\n")
    return head + "\n".join(_fmt(e, policy) for e in vals)


# --- a thin object wrapper (binds a path + a policy) ---------------------------

class Ledger:
    """A path + a policy. Every method routes its write through the firewall.

    The path is confined to ``root`` (defaults to the ledger file's own directory).
    A stranger uses their own ontology simply by passing their own ``LimitPolicy``.
    """

    def __init__(self, path, policy: LimitPolicy = DEFAULT_POLICY, root=None, id_prefix="ll-"):
        self.path = Path(path)
        self.root = Path(root) if root is not None else self.path.resolve().parent
        self.policy = policy
        self.id_prefix = id_prefix

    def load(self) -> list[dict]:
        return load_events(self.path, self.root)

    def state(self) -> dict[str, dict]:
        return fold_events(self.load())

    def add(self, limit, domain, cls, note=None):
        ev = add_limit(self.load(), limit, domain, cls, note, prefix=self.id_prefix)
        return append_event(ev, self.path, self.root, self.policy)

    def cross(self, lid, crossing, proof, joint=False, load_bearing=False, critic=None):
        ok, ev, msg = cross_limit(self.load(), lid, crossing, proof, joint=joint,
                                  load_bearing=load_bearing, critic=critic, policy=self.policy)
        if not ok:
            return False, None, msg
        ev = append_event(ev, self.path, self.root, self.policy)
        return True, ev, msg

    def park(self, lid, why):
        return self._restatus(lid, "parked", why)

    def hard(self, lid, why):
        return self._restatus(lid, self.policy.hard_status, why)

    def _restatus(self, lid, status, why):
        ok, ev, msg = _restatus(self.load(), lid, status, why, policy=self.policy)
        if not ok:
            return False, None, msg
        ev = append_event(ev, self.path, self.root, self.policy)
        return True, ev, msg

    def note(self, lid, text):
        ok, ev, msg = note_limit(self.load(), lid, text, policy=self.policy)
        if not ok:
            return False, None, msg
        ev = append_event(ev, self.path, self.root, self.policy)
        return True, ev, msg

    def query(self, status=None, domain=None, cls=None):
        return query_ledger(self.load(), status, domain, cls)

    def render(self) -> str:
        return render(self.load(), self.policy)
