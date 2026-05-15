"""Curated display-date overlay.

The upstream CSV's ``incident_date`` field is point-shaped and lossy:
~60% of cards have null (FBI omnibus files cover decade-spanning
ranges), and some cards carry demonstrably-wrong dates (D23 has
10/31/2023 in the CSV but the MISREP body's Zulu DTGs place the
sortie on October 24).

The fix isn't "leave null" or "guess." It's a curated `display_date`
per card with cited evidence, stored in
``data/display_dates.json`` as an overlay. After CSV parsing,
``merge_display_dates`` applies the overlay to the parsed cards,
preserving the original CSV value in ``manifest_incident_date_raw``
for audit. Cards without an overlay row are untouched.

See ``.paircoder/plans/display-date-curation.md`` for the full
editorial bar (every entry carries cited evidence; document body
wins on conflicts; abstentions are first-class).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.scrape.types import CardMetadata


@dataclass(frozen=True)
class DisplayDateEntry:
    """One row of the curated overlay.

    Either ``display_date`` (a point date YYYY-MM-DD or YYYY) is set,
    OR ``display_date_abstention`` is set with a documented reason —
    not both. The schema permits both fields to be present on the
    underlying JSON row for forward-compat, but the canonical state is
    "one or the other."
    """

    card_id: str
    display_date: str | None = None
    display_date_range: tuple[str, str] | None = None
    display_date_evidence: str | None = None
    display_date_evidence_card_ref: str | None = None
    display_date_curator: str | None = None
    display_date_approved_at: str | None = None
    display_date_abstention: str | None = None


def _entry_from_row(row: dict[str, Any]) -> DisplayDateEntry | None:
    """Validate + normalize a single overlay row. Returns None if
    the row is missing a card_id (which makes the row unusable).
    Forward-compatible: extra fields are ignored, missing optionals
    default to None."""
    card_id = row.get("card_id")
    if not isinstance(card_id, str) or not card_id:
        return None

    rng = row.get("display_date_range")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, str) for x in rng):
        rng_tuple: tuple[str, str] | None = (rng[0], rng[1])
    else:
        rng_tuple = None

    return DisplayDateEntry(
        card_id=card_id,
        display_date=row.get("display_date"),
        display_date_range=rng_tuple,
        display_date_evidence=row.get("display_date_evidence"),
        display_date_evidence_card_ref=row.get("display_date_evidence_card_ref"),
        display_date_curator=row.get("display_date_curator"),
        display_date_approved_at=row.get("display_date_approved_at"),
        display_date_abstention=row.get("display_date_abstention"),
    )


def load_display_dates(path: Path) -> dict[str, DisplayDateEntry]:
    """Load the curated overlay from ``data/display_dates.json``.

    Returns ``{card_id: entry}`` for every well-formed row. Missing
    file → empty dict (overlay is optional; an unbuilt overlay
    shouldn't crash the manifest build). Malformed JSON → empty dict
    with a logged note (caller can detect via len()==0).

    Rows missing ``card_id`` are skipped silently — they're the
    legitimate failure mode of an incomplete operator review session.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    entries: list[dict[str, Any]] = data.get("entries", []) if isinstance(data, dict) else []
    out: dict[str, DisplayDateEntry] = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        entry = _entry_from_row(row)
        if entry is None:
            continue
        out[entry.card_id] = entry
    return out


def merge_display_dates(
    cards: list[CardMetadata],
    overlay: dict[str, DisplayDateEntry],
) -> list[CardMetadata]:
    """Apply the curated overlay to a list of parsed cards.

    For each card_id present in the overlay, the returned card carries
    the curated date fields PLUS a ``manifest_incident_date_raw``
    snapshot of the CSV's original incident_date (so the audit trail
    survives the merge). Cards without an overlay row pass through
    unchanged.

    Pure: returns new ``CardMetadata`` instances; the input list and
    its members are not mutated.
    """
    out: list[CardMetadata] = []
    for card in cards:
        entry = overlay.get(card.card_id)
        if entry is None:
            out.append(card)
            continue
        out.append(
            card.model_copy(update={
                "display_date": entry.display_date,
                "display_date_range": entry.display_date_range,
                "display_date_evidence": entry.display_date_evidence,
                "display_date_evidence_card_ref": entry.display_date_evidence_card_ref,
                "display_date_curator": entry.display_date_curator,
                "display_date_approved_at": entry.display_date_approved_at,
                "display_date_abstention": entry.display_date_abstention,
                "manifest_incident_date_raw": card.incident_date,
            })
        )
    return out
