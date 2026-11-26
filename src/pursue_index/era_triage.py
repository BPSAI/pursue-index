"""Triage rows for undated cards (spec §4a / §5).

A card with no resolvable document era is listed explicitly rather than
bucketed. Each row's ``reason`` states the actual state of its date fields, so
a row never contradicts a populated ``incident_date`` or ``display_date``.
"""

from __future__ import annotations

from typing import Any

from pursue_index.era_models import DOCUMENT_DATE_FIELDS, CardEra

__all__ = ["triage_entry", "triage_reason"]


def triage_reason(card: dict[str, Any]) -> str:
    """Why a card is undated, stating the actual state of its date fields."""
    for name in DOCUMENT_DATE_FIELDS:
        raw = card.get(name)
        if raw is not None and str(raw).strip():
            return f"{name} present but not a resolvable date: {raw}"
    if card.get("release_date"):
        return (
            "only a war.gov release_date is present, which is a publication date, "
            "not a document era"
        )
    return "no date on any manifest field"


def triage_entry(card_era: CardEra, card: dict[str, Any]) -> dict[str, Any]:
    """An explicit triage row for an undated card — never silently bucketed."""
    reason = triage_reason(card)
    return {
        "card_id": card_era.card_id,
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
