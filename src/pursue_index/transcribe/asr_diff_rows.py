"""AUD row logic shared by the ``asr-diff run`` preview and the ``asr-diff live`` plan.

Both commands walk the same rows and must agree on them, so the row
duration lives here once.
"""

from __future__ import annotations


def row_duration(meta: dict, row: dict) -> float:
    """A row's audio seconds: its own ``audio_duration_s``, else the top-level
    ``meta.audio_duration_s`` for single-row meta only (older single-row meta
    keeps it there; a multi-row card's total is not any one row's). Missing,
    unreadable or negative reads as 0."""
    value = row.get("audio_duration_s")
    if value is None and len(meta.get("rows") or []) <= 1:
        value = meta.get("audio_duration_s")
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
