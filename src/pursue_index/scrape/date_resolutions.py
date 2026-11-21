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
repeated ``(card_id, field)`` the last row wins, whatever its kind.

An **acknowledged-unknown** entry records instead that a date stays
unknown: ``value`` null or absent, ``status`` exactly
``acknowledged-unknown``, and a non-empty ``reason``, ``curator``,
``approved_at`` and ``upstream_value`` (the exact 2-digit upstream string
acknowledged); one missing any of those, with an ``approved_at`` that is
not a timezone-aware ISO-8601 timestamp, or with an ``upstream_value`` not
in ``M/D/YY`` form is skipped. An entry of either kind whose ``reason``,
``curator``, ``approved_at`` or ``upstream_value`` is still a worklist
template placeholder (``<...>``) is skipped too, so a pasted, unedited
entry never clears anything. While upstream's value
is ``upstream_value`` the field is left as it is (never given a date) and
the row is reported as acknowledged, not UNRESOLVED (``year_outcome``).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pursue_index.scrape.year_resolve import TWO_DIGIT

__all__ = ["ACKNOWLEDGED", "ACK_ENTRY_SHAPE", "DATE_RESOLUTIONS_FILE", "ENTRY_SHAPE",
           "Overlay", "load_date_resolutions"]

# Repo-relative path, shown to the operator in the worklist.
DATE_RESOLUTIONS_FILE = "data/date_resolutions.json"
ENTRY_SHAPE = ('{"card_id": "<card_id>", "field": "<field>", "value": "M/D/YYYY", '
               '"curator": "<who>", "approved_at": "<ISO-8601 UTC>"}')
ACKNOWLEDGED = "acknowledged-unknown"
ACK_ENTRY_SHAPE = ('{"card_id": "<card_id>", "field": "<field>", "value": null, '
                   f'"status": "{ACKNOWLEDGED}", "reason": "<why>", "curator": "<who>", '
                   '"approved_at": "<ISO-8601 UTC>", "upstream_value": "M/D/YY"}')
_FIELDS = ("release_date", "incident_date")
_ACK_KEYS = ("reason", "curator", "approved_at", "upstream_value")

# (card_id, field) -> {"value", "curator", "approved_at"}, or for an
# acknowledged-unknown entry {"value": None, "status", "reason", "curator",
# "approved_at", "upstream_value"}
Overlay = dict[tuple[str, str], dict[str, Any]]


_PLACEHOLDER = re.compile(r"^<.*>$")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _placeholder(row: dict[str, Any]) -> bool:
    """Whether a provenance field still holds a worklist template ``<...>``."""
    return any(isinstance(v := row.get(k), str) and _PLACEHOLDER.match(v.strip())
               for k in _ACK_KEYS)


def _utc_stamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _acknowledged(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("value") is not None or not all(_text(row.get(k)) for k in _ACK_KEYS):
        return None
    if not (_utc_stamp(row["approved_at"]) and TWO_DIGIT.match(row["upstream_value"])):
        return None
    return {"value": None, "status": ACKNOWLEDGED, "reason": row["reason"],
            "curator": row["curator"], "approved_at": row["approved_at"],
            "upstream_value": row["upstream_value"].strip()}


def _entry(row: Any) -> tuple[tuple[str, str], dict[str, Any]] | None:
    if not isinstance(row, dict):
        return None
    card_id, fld, value = row.get("card_id"), row.get("field"), row.get("value")
    if not (isinstance(card_id, str) and card_id and fld in _FIELDS) or _placeholder(row):
        return None
    if row.get("status") == ACKNOWLEDGED:
        parsed = _acknowledged(row)
        return None if parsed is None else ((card_id, fld), parsed)
    if not _text(value):
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
