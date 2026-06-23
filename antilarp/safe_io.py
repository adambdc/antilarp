"""safe_io.py — confined, never-raising I/O primitives.

Path-scoping to a supplied root, atomic writes, crash-proof reads, defensive
JSONL parsing. The low layer that keeps the ledger restart-safe: a half-written
file or a stray symlink path can't corrupt the log the firewall exists to protect.

stdlib-only, zero-dependency, zero-network. Vendored intact so the standalone repo
has no external coupling — the caller supplies the confinement `root` explicitly
(no fixed directory layout is assumed).
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

Pathish = str | os.PathLike[str]


def resolve_in_root(path: Pathish, root: Pathish) -> Path | None:
    """Resolve ``path`` only if it remains inside ``root``.

    Relative paths are interpreted under ``root``. Absolute paths are accepted
    only when their resolved target is inside ``root``. Any ``..`` component,
    symlink escape, symlink loop, or filesystem resolution error returns ``None``.
    This is the generic anti-symlink-escape guard the writer leans on.
    """
    raw_path = Path(path)
    if ".." in raw_path.parts:
        return None

    try:
        safe_root = Path(root).resolve()
        candidate = raw_path if raw_path.is_absolute() else safe_root / raw_path
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return None

    try:
        resolved.relative_to(safe_root)
    except ValueError:
        return None
    return resolved


def safe_read_text(path: Pathish, root: Pathish, max_bytes: int = 5_000_000) -> str:
    """Confined, bounded text read that never raises.

    Returns an empty string for any confinement violation, unsafe target, oversized
    file, invalid byte limit, or ``OSError``. Bytes are decoded as UTF-8 with
    replacement so a corrupt or mixed-encoding file cannot crash a read.
    """
    if max_bytes < 0:
        return ""

    resolved = resolve_in_root(path, root)
    if resolved is None:
        return ""

    try:
        st = resolved.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            return ""
        with resolved.open("rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return ""

    if len(data) > max_bytes:
        return ""
    return data.decode("utf-8", errors="replace")


def atomic_write(path: Pathish, text: str) -> None:
    """Atomically write text via a same-directory replace.

    The temporary file is created in the target directory, flushed, fsynced, and
    then installed with ``os.replace``. A power cut mid-write leaves the prior file
    intact. Callers remain responsible for choosing a confined path before writing.
    """
    target = Path(path)
    parent = target.parent
    tmp_name: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_name = fh.name
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tmp_name, target)
        tmp_name = None

        try:
            dir_fd = os.open(parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def iter_jsonl_dicts(path: Pathish, root: Pathish,
                     warn: bool = False) -> Iterator[dict[str, Any]]:
    """Yield valid dict records from a confined JSONL file.

    Blank, malformed, non-dict, unsafe, unreadable, and oversized inputs are
    silently skipped. The iterator never raises for bad JSONL content.

    With ``warn=True``, a malformed or non-dict line is reported to stderr
    (``path:lineno``) instead of vanishing — for a load-bearing log like the
    ledger, where a corrupted entry must nag, not silently disappear. The default
    stays silent; warn never changes what is *yielded* (no new raises).
    """
    for lineno, line in enumerate(safe_read_text(path, root).splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, RecursionError) as e:
            if warn:
                print(f"warning: {path}:{lineno}: skipped malformed JSON ({e})",
                      file=sys.stderr)
            continue
        if isinstance(record, dict):
            yield record
        elif warn:
            print(f"warning: {path}:{lineno}: skipped non-dict JSON record",
                  file=sys.stderr)
