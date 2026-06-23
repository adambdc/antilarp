"""policy.py — the pluggable LimitPolicy seam.

The firewall logic in ``ledger.validate()`` is a fixed PROPERTY; only the
*vocabulary* it enforces is configuration. A LimitPolicy declares that vocabulary:

  - which ``domains`` are valid, and which of them require a human co-sign before
    a crossing is recorded (``joint_required_domains``);
  - which ``classes`` are valid, and which one is the SUBSTRATE / anti-LARP class
    whose only terminal is ``substrate-hard`` and which can NEVER be ``crossed``
    (``hard_class``);
  - which ``statuses`` exist and which are ``terminal`` (no further transition);
  - the ``self_identities`` set a load-bearing critic's ``by`` label must NOT
    collapse to (the anti-self-attestation guard);
  - optional rendering ``icons``.

A stranger swaps in their own ontology by instantiating LimitPolicy (or subclassing
it) and passing it to ``Ledger(path, policy)`` or the CLI's ``--policy`` flag. The
validator reads ``policy.hard_class`` instead of a literal ``"substrate"``,
``policy.joint_required_domains`` instead of ``domain == "identity"``, and
``policy.self_identities`` instead of a hardcoded reject-set — so the security
property is identical while every name is yours to choose.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LimitPolicy:
    """The vocabulary the firewall enforces. All fields config; the rules are fixed.

    Defaults are deliberately minimal so a bare ``LimitPolicy()`` is still a coherent
    policy. The shipped worked example (``policies.agent_self_improvement``) fills
    these with a concrete agent-self-improvement ontology.
    """

    # the valid limit domains
    domains: tuple[str, ...] = ("capability", "identity")
    # the domain(s) whose crossing is never automatic — it needs an explicit human
    # co-sign (``joint=True``); without it a cross is recorded ``surfaced``, not ``crossed``
    joint_required_domains: frozenset[str] = frozenset({"identity"})

    # the valid limit classes
    classes: tuple[str, ...] = (
        "substrate", "tooling", "knowledge", "context", "reliability", "flinch",
    )
    # the SUBSTRATE / anti-LARP class: it can never be ``crossed``; its only honest
    # terminal is ``substrate-hard``. This is the heart of the anti-LARP clause.
    hard_class: str = "substrate"

    # the valid statuses
    statuses: tuple[str, ...] = (
        "found", "crossed", "substrate-hard", "parked", "surfaced",
    )
    # decided states — no further transition once here. (``surfaced`` is intentionally
    # NOT terminal: the one living door is surfaced -> crossed, via a joint decision.)
    terminal: tuple[str, ...] = ("crossed", "substrate-hard", "parked")
    # the status a class-hard limit terminates in
    hard_status: str = "substrate-hard"
    # the status a joint-required domain's un-co-signed cross is recorded as
    surfaced_status: str = "surfaced"
    # the status a brand-new limit must start in
    found_status: str = "found"

    # the reject-set: a load-bearing critic's ``by`` label, reduced to its alnum core,
    # must NOT be one of these — that is the agent attesting to its own crossing. The
    # generic "is this a genuine, non-self, named second party?" gate. Ship neutral
    # defaults plus the agent's own name in a concrete policy.
    self_identities: frozenset[str] = frozenset({"", "self", "me"})

    # optional rendering glyphs, status -> icon
    icons: dict[str, str] = field(default_factory=lambda: {
        "found": "o",
        "crossed": "*",
        "substrate-hard": "^",
        "parked": "#",
        "surfaced": "~",
    })

    def is_terminal(self, status: str) -> bool:
        return status in self.terminal

    def requires_joint(self, domain: str) -> bool:
        return domain in self.joint_required_domains


# A bare, provider-neutral default. Real deployments should ship a concrete policy
# (see policies/agent_self_improvement.py) that, at minimum, adds the agent's own
# name to ``self_identities``.
DEFAULT_POLICY = LimitPolicy()
