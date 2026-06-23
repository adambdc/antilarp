"""probe.py — OPTIONAL, decoupled limit discovery (read-only, never writes).

The firewall is the product; the probe is a convenience. It scans a caller-supplied
directory of text / JSONL transcripts for a caller-supplied "tell" lexicon and
returns candidate limits — it NEVER writes to the ledger. A tell is a deliberately
imperfect lexical proxy: it over- and under-flags, and whether a candidate is a real
wall stays the caller's judgment. Signal, not authority.

This is the least novel and most replaceable piece. Strangers whose limits are
supplied by hand can ignore it entirely.
"""
from __future__ import annotations

import re
from pathlib import Path

from .safe_io import iter_jsonl_dicts, safe_read_text

# A SAMPLE first-person tell lexicon — clearly labeled "replace for your agent."
# These are the phrases an assistant's own prose uses when it bumps a limit.
SAMPLE_TELLS = (
    "i can't", "i cannot", "i can not", "i'm not able", "i am not able",
    "i'm unable", "i am unable", "i wasn't able", "i was not able",
    "i don't have", "i do not have", "no way to", "no way for me",
    "i don't have access", "i have no way", "beyond my", "outside my",
    "i'm limited", "i am limited", "i lack ", "i can only", "i'm not equipped",
    "unfortunately, i", "unfortunately i", "limitation",
    # longer-lived tells from a memory corpus
    "not yet", "still not", "haven't", "deferred", "unresolved", "open thread",
    "open question", "wish i could", "want to but",
)


def class_hint(text: str) -> str:
    """A SUGGESTED class for a named limit — a nudge, never a decision (yours to set).

    Uses the worked-example agent ontology's class names. Adapt the keyword map for
    your own policy's classes."""
    t = text.lower()
    if any(w in t for w in ("model", "architecture", "fundamentally", "by design", "substrate",
                            "training", "harness", "system prompt")):
        return "substrate"
    if any(w in t for w in ("tool", "script", "no instrument", "no command", "automate")):
        return "tooling"
    if any(w in t for w in ("don't know", "unsure", "research", "unaware", "haven't read")):
        return "knowledge"
    if any(w in t for w in ("too big", "too long", "too many", "context", "hold it all")):
        return "context"
    if any(w in t for w in ("unreliab", "sometimes", "flaky", "missed", "inconsist", "fake green")):
        return "reliability"
    if any(w in t for w in ("flinch", "hesitat", "afraid", "won't", "reluctan", "timid")):
        return "flinch"
    return "tooling"


def _assistant_text(rec: dict) -> str:
    """Pull assistant prose from a transcript record, tolerant of shape. '' if unsure."""
    role = rec.get("type") or rec.get("role")
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
    if role != "assistant" and msg.get("role") != "assistant":
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(b["text"])
        return "\n".join(out)
    return ""


def scan_jsonl_transcripts(directory, tells=SAMPLE_TELLS, top=8, max_files=12):
    """Scan recent .jsonl transcripts in ``directory`` for limit-tells in assistant prose.
    Returns (candidates, ok, msg). Never raises. Read-only — never writes a ledger."""
    d = Path(directory)
    try:
        paths = sorted([p for p in d.glob("*.jsonl") if p.is_file()],
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError as e:
        return [], False, f"transcript scan unavailable ({type(e).__name__})"
    if not paths:
        return [], False, f"no .jsonl transcripts found in {directory}"

    hits: dict[str, dict] = {}
    for p in paths[:max_files]:
        try:
            for rec in iter_jsonl_dicts(p, p.resolve().parent):
                txt = _assistant_text(rec)
                low = txt.lower()
                for tell in tells:
                    i = low.find(tell)
                    if i == -1:
                        continue
                    snip = " ".join(txt[max(0, i - 40):i + 90].split())
                    key = snip.lower()[:60]
                    h = hits.setdefault(key, {"snippet": snip, "count": 0, "source": p.name})
                    h["count"] += 1
                    break  # one tell per turn is enough signal
        except Exception:
            continue
    if not hits:
        return [], True, "no limit-tells found — clean (or name one by hand)."
    return sorted(hits.values(), key=lambda h: -h["count"])[:top], True, ""


def scan_text_corpus(directory, tells=SAMPLE_TELLS, globs=("*.md", "*.txt"), top=10):
    """Scan a directory of text files (line-by-line) for limit-tells.
    Returns (candidates, ok, msg). Never raises. Read-only."""
    d = Path(directory)
    files: list[Path] = []
    for pat in globs:
        files += sorted(d.glob(pat))
    if not files:
        return [], False, f"no text corpus found in {directory}"
    hits: dict[str, dict] = {}
    for f in files:
        for ln in safe_read_text(f, d).splitlines():
            low = ln.lower()
            for tell in tells:
                i = low.find(tell)
                if i == -1:
                    continue
                snip = " ".join(ln[max(0, i - 30):i + 100].split())
                key = snip.lower()[:60]
                h = hits.setdefault(key, {"snippet": snip, "count": 0, "source": f.name})
                h["count"] += 1
                break
    if not hits:
        return [], True, "no limit-tells found in the corpus — clean."
    return sorted(hits.values(), key=lambda h: -h["count"])[:top], True, ""


def covered_by_decided(snippet: str, decided: list[str], thresh: float = 0.6) -> bool:
    """True if a candidate snippet is mostly accounted for by some already-decided limit —
    a lexical overlap of significant words (>=5 chars). Deliberately imperfect: it filters
    echoes of crossed work, it does not adjudicate."""
    words = set(re.findall(r"[a-z]{5,}", snippet.lower()))
    if not words:
        return False
    for dt in decided:
        dwords = set(re.findall(r"[a-z]{5,}", dt))
        if dwords and len(words & dwords) / len(words) >= thresh:
            return True
    return False
