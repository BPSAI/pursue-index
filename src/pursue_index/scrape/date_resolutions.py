"""Manual resolutions for 2-digit-year dates no rule could restore.

A committed overlay, ``data/date_resolutions.json``, in the same shape as
the curated ``data/display_dates.json`` overlay (``display_dates``): an
``entries`` list, one row per ``(card_id, field)``, each naming who
resolved it and when::

    {"entries": [{"card_id": "<card_id>", "field": "incident_date",
                  "value": "M/D/YYYY", "curator": "<who>",
                  "approved_at": "<ISO-8601 UTC>"}]}

``year_resolve`` treats an entry as the highest-precedence evidence
(``manual``), honoured only when its month, day and last two year digits
match upstream's 2-digit value; otherwise the row stays UNRESOLVED
(``manual_mismatch``). A missing or malformed file is an empty overlay,
and a row missing ``card_id``, ``field`` or ``value`` -- or naming a field
other than ``release_date`` / ``incident_date`` -- is skipped. For a
repeated ``(card_id, field)`` the last row wins.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["DATE_RESOLUTIONS_FILE", "ENTRY_SHAPE", "Overlay", "load_date_resolutions"]

# Repo-relative path, shown to the operator in the worklist.
DATE_RESOLUTIONS_FILE = "data/date_resolutions.json"
ENTRY_SHAPE = ('{"card_id": "<card_id>", "field": "<field>", "value": "M/D/YYYY", '
               '"curator": "<who>", "approved_at": "<ISO-8601 UTC>"}')
_FIELDS = ("release_date", "incident_date")

# (card_id, field) -> {"value", "curator", "approved_at"}
Overlay = dict[tuple[str, str], dict[str, Any]]


def _entry(row: Any) -> tuple[tuple[str, str], dict[str, Any]] | None:
    if not isinstance(row, dict):
        return None
    card_id, fld, value = row.get("card_id"), row.get("field"), row.get("value")
    if not (isinstance(card_id, str) and card_id and fld in _FIELDS
            and isinstance(value, str) and value.strip()):
        return None
    return (card_id, fld), {"value": value.strip(), "curator": row.get("curator"),
                            "approved_at": row.get("approved_at")}


def load_date_resolutions(path: Path) -> Overlay:
    """The overlay at ``path``; empty when the file is absent or malformed."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    rows = data.get("entries", []) if isinstance(data, dict) else []
    out: Overlay = {}
    for row in rows if isinstance(rows, list) else []:
        if (parsed := _entry(row)) is not None:
            out[parsed[0]] = parsed[1]
    return out
