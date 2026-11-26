"""Triage rows for undated cards (spec §4a / §5).

A card with no resolvable document era is listed explicitly rather than
bucketed. Each row's ``reason`` states the actual state of its date fields, so
a row never contradicts a populated ``incident_date`` or ``display_date``.
"""

from __future__ import annotations

from typing import Any

from pursue_index.era_dates import MODERN_MIN_YEAR, SLASH_GUARDED_FIELDS, parse_year_detail
from pursue_index.era_models import DOCUMENT_DATE_FIELDS, CardEra

__all__ = ["triage_entry", "triage_reason"]


def _held_for_century(field: str, raw: Any) -> bool:
    """True when a numeric M/D/YYYY 2015+ year was held back for lack of corroboration."""
    parsed = parse_year_detail(raw)
    return (
        parsed.year is not None
        and parsed.slash_dated
        and not parsed.pivot_derived
        and field in SLASH_GUARDED_FIELDS
        and parsed.year >= MODERN_MIN_YEAR
    )


def triage_reason(card: dict[str, Any]) -> str:
    """Why a card is undated, stating the actual state of its date fields."""
    for name in DOCUMENT_DATE_FIELDS:
        raw = card.get(name)
        if raw is not None and str(raw).strip():
            if _held_for_century(name, raw):
                return (
                    f"{name} {raw} present but its century is uncorroborated "
                    "(numeric M/D/YYYY year; no corroborating field); held undated"
                )
            return f"{name} present but not a resolvable date: {raw}"
    if card.get("release_date"):
        return (
            "only a war.gov release_date is present, which is a publication date, "
            "not a document era"
        )
    return "no date on any manifest field"


def triage_entry(card_era: CardEra, card: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    """An explicit triage row for an undated card — never silently bucketed.

    ``reason`` overrides the date-field reason, as a row of a conflicting file does.
    """
    reason = reason if reason is not None else triage_reason(card)
    return {
        "card_id": card_era.card_id,
        "row_key": card_era.row_key,
        "identifier": card_era.identifier,
        "title": card_era.title,
        "agency": card_era.agency,
        "available_dates": {
            "display_date": card.get("display_date"),
            "incident_date": card.get("incident_date"),
            "release_date": card.get("release_date"),
        },
        "reason": reason,
    }
