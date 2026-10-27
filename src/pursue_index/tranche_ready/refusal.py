"""Build the body of a refused tranche-ready record without leaking its text.

The refusal body is filed as a PUBLIC issue, and record free text (titles,
signals) is upstream-controlled. So the body reports only field paths, the
rule, both records' sha256 and byte size, and the local file holding the full
diff -- never a value. Anything quoted anyway goes through :func:`neutralize`,
and the whole body is bounded by :func:`cap`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["MAX_BODY_BYTES", "cap", "changed_paths", "describe_conflict", "full_diff", "neutralize"]

MAX_BODY_BYTES = 8 * 1024
_MAX_PATHS = 40
_MAX_PATH_CHARS = 120
_STRIP: dict[int, str | None] = {ord(c): None for c in "`<>"}
_STRIP[ord("@")] = "\uff20"
_STRIP.update({c: " " for c in [*range(32), 127] if c not in (9, 10)})


def neutralize(text: str) -> str:
    """No backticks or angle brackets; ``@`` becomes its fullwidth form (U+FF20); no controls."""
    return text.translate(_STRIP)


def cap(text: str, limit: int = MAX_BODY_BYTES) -> str:
    """``text`` cut to at most ``limit`` UTF-8 bytes."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[: limit - 16].decode("utf-8", "ignore") + "\n[truncated]"


def _canonical(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def changed_paths(a: Any, b: Any, where: str = "") -> list[str]:
    """``/``-joined paths at which ``a`` and ``b`` differ (sorted, unbounded)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{where}/{key}" if where else str(key)
            if key not in a or key not in b:
                out.append(sub)
            else:
                out += changed_paths(a[key], b[key], sub)
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = []
        for i in range(max(len(a), len(b))):
            sub = f"{where}/{i}" if where else str(i)
            if i >= len(a) or i >= len(b):
                out.append(sub)
            else:
                out += changed_paths(a[i], b[i], sub)
        return out
    return [] if a == b and type(a) is type(b) else [where or "<root>"]


def _side(label: str, doc: Any) -> str:
    raw = _canonical(doc)
    return f"{label} sha256={hashlib.sha256(raw).hexdigest()} bytes={len(raw)}"


def describe_conflict(path: Any, stored: Any, recomputed: Any) -> str:
    """Value-free append-only refusal text, bounded by :data:`MAX_BODY_BYTES`."""
    paths = changed_paths(stored, recomputed)
    shown = [neutralize(p)[:_MAX_PATH_CHARS] for p in paths[:_MAX_PATHS]]
    more = f"\n  ... and {len(paths) - len(shown)} more" if len(paths) > len(shown) else ""
    lines = [
        f"tranche-ready outputs are append-only: {neutralize(str(path))} already exists"
        " and the recomputed content disagrees with it; refusing to rewrite.",
        _side("  stored:    ", stored),
        _side("  recomputed:", recomputed),
        f"  differing fields ({len(paths)}):",
        *(f"    {p}" for p in shown),
    ]
    return cap("\n".join(lines) + more)


def full_diff(stored: Any, recomputed: Any) -> str:
    """Both records in full (local file only -- never posted)."""
    return json.dumps({"stored": stored, "recomputed": recomputed}, indent=2, sort_keys=True) + "\n"
