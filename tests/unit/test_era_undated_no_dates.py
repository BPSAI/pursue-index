"""An undated card carries no year, date source or raw date in its record.

release_date is a publication date, never a document era, so it must not
leak into the card-era record of a card that has no document date.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.era_bucketing import bucket
from pursue_index.era_models import Era

_HELD = ("3a0d83f3e51179db", "ff3939f95d878062", "71758de42a2df926")
_ARTIFACT = Path(__file__).resolve().parents[2] / "data" / "provenance" / "era-buckets.json"


def _card(card_id: str, **dates: str) -> dict[str, object]:
    return {"card_id": card_id, "title": f"Card {card_id}", "agency": "DOW", **dates}


def test_guard_held_cards_carry_no_year_or_source() -> None:
    cards = [_card(c, incident_date="6/7/2024", release_date="5/8/2026") for c in _HELD]
    result = bucket({"cards": cards})
    assert len(result.cards) == 3
    for row in result.cards:
        assert row.era is Era.UNDATED
        assert row.year is None
        assert row.date_source is None
        assert row.raw_date is None
        assert row.to_dict()["year"] is None


def test_release_only_and_no_date_cards_carry_nothing() -> None:
    result = bucket({"cards": [_card("r", release_date="5/8/2026"), _card("n")]})
    for row in result.cards:
        assert (row.era, row.year, row.date_source, row.raw_date) == (Era.UNDATED, None, None, None)


def test_dated_card_keeps_year_and_source() -> None:
    card = _card("d", incident_date="2019-03-04", release_date="5/8/2026")
    (row,) = bucket({"cards": [card]}).cards
    assert row.era is Era.MODERN_OPERATIONAL
    assert row.year == 2019
    assert row.date_source == "incident_date"


def test_published_artifact_has_no_dated_looking_undated_row() -> None:
    cards = json.loads(_ARTIFACT.read_text())["cards"]
    undated = [c for c in cards if c["era"] == "undated"]
    assert undated
    bad = [c for c in undated if c["year"] is not None or c["date_source"] is not None]
    assert bad == []
