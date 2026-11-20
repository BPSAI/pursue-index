"""The per-card marker for an open (UNRESOLVED) 2-digit-year date.

An UNRESOLVED field is written to the snapshot as the prior's stored 4-digit
value, unchanged, or EMPTY when the prior stores none (``year_outcome``), so
a 2-digit value is never stored as the next poll's prior and good published
data is never emptied. What stays open is carried instead in
the card's ``raw`` dict under ``MARKER_KEY``: a list of
``{field, raw, reason, first_flagged_in, first_flagged_at}`` -- the
upstream value, why no rule fixed it, and the tranche (``csv_sha256``) and
fetch time that first flagged it.

``raw`` is the place because it already holds upstream's string under the
CSV column name, it is copied verbatim when a snapshot is promoted to
``latest.json``, and it is outside every field diff (``DIFF_SKIP_FIELDS``),
so no card schema change and no new field change.

On the next poll a row whose prior marker has the same upstream value
carries that marker (``first_flagged_*`` kept)
as an open item, not a new flag; a different upstream value is a new flag.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter

__all__ = ["MARKER_KEY", "carries", "iso", "new_marker", "open_entry", "prior_markers",
           "with_markers"]

MARKER_KEY = "_date_unresolved"
_DATETIME = TypeAdapter(datetime)


def iso(value: datetime | None) -> str | None:
    """A fetch time as the snapshot serializes it."""
    return None if value is None else _DATETIME.dump_python(value, mode="json")


def prior_markers(prior_rows: Sequence[Mapping[str, Any]]
                  ) -> dict[tuple[Any, str], dict[str, Any]]:
    """``(card_id, field) -> marker`` over every prior row's ``raw``."""
    out: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in prior_rows:
        markers = (row.get("raw") or {}).get(MARKER_KEY)
        for m in markers if isinstance(markers, list) else []:
            if isinstance(m, dict) and isinstance(m.get("field"), str):
                out[(row.get("card_id"), m["field"])] = m
    return out


def carries(prior: Mapping[str, Any] | None, raw: str) -> bool:
    """Whether ``prior`` (a marker or None) is the same open item as ``raw``."""
    return prior is not None and str(prior.get("raw") or "").strip() == raw.strip()


def new_marker(field: str, raw: str, reason: str, tranche: str | None,
               fetched_at: str | None) -> dict[str, Any]:
    return {"field": field, "raw": raw, "reason": reason,
            "first_flagged_in": tranche, "first_flagged_at": fetched_at}


def open_entry(entry: Mapping[str, Any], marker: Mapping[str, Any]) -> dict[str, Any]:
    """A report entry for a carried item: ``entry`` plus when it was first flagged."""
    return {**entry, "reason": marker["reason"],
            "first_flagged_in": marker.get("first_flagged_in"),
            "first_flagged_at": marker.get("first_flagged_at")}


def with_markers(raw: Mapping[str, Any], markers: list[dict[str, Any]]) -> dict[str, Any]:
    """A copy of ``raw`` holding ``markers`` (key dropped when there are none)."""
    out = {k: v for k, v in raw.items() if k != MARKER_KEY}
    if markers:
        out[MARKER_KEY] = markers
    return out
