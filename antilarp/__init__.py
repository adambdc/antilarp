"""antilarp — the anti-LARP firewall for a self-improving agent's limit ledger.

A self-improving agent keeps an append-only ledger of its own limits and crosses
them — but a mechanized, fail-closed validator makes it structurally impossible to
record a fake win. The agent can never bank "I exceeded my substrate," can never
quietly cross an identity-class limit without a human co-sign, and a load-bearing
crossing is refused unless a DECORRELATED second mind confirms it.

The firewall is not prose; it is the test suite (``tests/test_firewall.py``).
"""
from .ledger import (
    Ledger,
    add_limit,
    append_event,
    cross_limit,
    fold_events,
    load_events,
    next_id,
    note_limit,
    query_ledger,
    render,
    validate,
)
from .policy import DEFAULT_POLICY, LimitPolicy

__all__ = [
    "Ledger",
    "LimitPolicy",
    "DEFAULT_POLICY",
    "validate",
    "append_event",
    "load_events",
    "fold_events",
    "next_id",
    "add_limit",
    "cross_limit",
    "note_limit",
    "query_ledger",
    "render",
]

__version__ = "0.1.0"
