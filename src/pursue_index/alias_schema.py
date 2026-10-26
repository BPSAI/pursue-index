"""Row schema for ``data/card-aliases.json``.

Every row names the rename (``old_card_id`` -> ``new_card_id``), how it was
established (``method``) and when (``established``). R7C.13 adds OPTIONAL
byte-change evidence -- ``old_byte_sha256`` / ``new_byte_sha256`` /
``change_nature`` -- written only where a classifier verdict is actually
known; rows without it (most of them) stay valid unchanged.
"""

from __future__ import annotations

from typing import Any

BASE_KEYS = ("old_card_id", "new_card_id", "method", "established")
EVIDENCE_KEYS = ("old_byte_sha256", "new_byte_sha256", "change_nature")
CHANGE_NATURES = ("metadata-only", "content-changed", "unknown")


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def alias_row_errors(row: dict[str, Any]) -> list[str]:
    """Human-readable schema violations for one alias row ([] when valid)."""
    errors = [f"{k}: required non-empty string" for k in BASE_KEYS
              if not _is_text(row.get(k))]
    errors += [f"{k}: must be a non-empty string when present" for k in EVIDENCE_KEYS
               if k in row and not _is_text(row[k])]
    nature = row.get("change_nature")
    if _is_text(nature) and nature not in CHANGE_NATURES:
        errors.insert(0, f"change_nature: {nature!r} not one of {CHANGE_NATURES}")
    return errors
