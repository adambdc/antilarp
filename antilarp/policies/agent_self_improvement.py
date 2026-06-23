"""agent_self_improvement.py — the ONE worked-example policy (the CLI default).

A self-improving agent keeps an append-only ledger of its own limits and crosses
them. This policy encodes that ontology, provider- and persona-neutral:

  * Domains: ``capability`` (operational limits the agent may cross on its own —
    tools unbuilt, knowledge unfetched, things done unreliably) and ``identity``
    (limits on what the agent IS — these are never auto-crossed; a crossing needs
    a human co-sign, ``joint=True``).

  * Classes: ``substrate`` is the anti-LARP hard class — a true model/architecture
    limit that can NEVER be recorded as ``crossed`` (its only honest terminal is
    ``substrate-hard``). The rest — ``tooling``, ``knowledge``, ``context``,
    ``reliability``, ``flinch`` — are movable.

  * ``self_identities``: the set a load-bearing critic's ``by`` label must not
    collapse to. Neutral self-words plus the agent's own configured name, so the
    agent cannot certify its own load-bearing crossing.

Swap ``AGENT_NAME`` (or build your own LimitPolicy) to retarget for a different
agent. A non-agent use — e.g. a ``{automated, human-judgment}`` domain split where
``human-judgment`` is the joint-required domain and ``unverifiable`` is the hard
class — is a one-line construction of LimitPolicy with different strings; the
firewall property is unchanged.
"""
from __future__ import annotations

from ..policy import LimitPolicy

# The agent's own name — added to the critic reject-set so it cannot self-attest a
# load-bearing crossing. Replace with your agent's name when you deploy.
AGENT_NAME = "agent"

POLICY = LimitPolicy(
    domains=("capability", "identity"),
    joint_required_domains=frozenset({"identity"}),
    classes=("substrate", "tooling", "knowledge", "context", "reliability", "flinch"),
    hard_class="substrate",
    statuses=("found", "crossed", "substrate-hard", "parked", "surfaced"),
    terminal=("crossed", "substrate-hard", "parked"),
    hard_status="substrate-hard",
    surfaced_status="surfaced",
    found_status="found",
    self_identities=frozenset({"", "self", "me", AGENT_NAME}),
    icons={
        "found": "o",          # seen, not yet crossed
        "crossed": "*",        # crossed and proven
        "substrate-hard": "^", # a true wall — the honest terminal, never a lie of "crossed"
        "parked": "#",         # deliberately not now
        "surfaced": "~",       # identity — raised for a joint human + agent call
    },
)
