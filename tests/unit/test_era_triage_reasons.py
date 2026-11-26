"""An undated_triage row must never contradict a populated document date.

A resolvable four-digit document date buckets the card by that year. A document
date that is present but cannot be resolved keeps the card undated, and the
triage reason states the raw value instead of claiming only a release_date.
"""

from __future__ import annotations

import pytest

from pursue_index.era_bucketing import bucket
from pursue_index.era_models import Era

_RELEASE_ONLY = "only a war.gov release_date is present"
_NO_DATE = "no date on any manifest field"


def _card(card_id: str, **dates: str | None) -> dict[str, object]:
    return {"card_id": card_id, "title": f"Card {card_id}", "agency": "DOW", **dates}


def _triage(card: dict[str, object]) -> list[dict[str, object]]:
    return bucket({"cards": [card]}).triage


@pytest.mark.parametrize(
    "incident,year", [("6/7/2024", 2024), ("8/31/2020", 2020), ("3/23/2026", 2026)]
)
def test_resolvable_four_digit_incident_date_buckets_the_card(incident: str, year: int) -> None:
    result = bucket(
        {"cards": [_card("a", incident_date=incident, release_date="5/8/2026")]}
    )
    assert result.triage == []
    assert result.cards[0].era is Era.MODERN_OPERATIONAL
    assert result.cards[0].year == year
    assert result.cards[0].date_source == "incident_date"


@pytest.mark.parametrize("raw", ["Undated", "5/24/2962"])
def test_unresolvable_incident_date_is_named_in_the_reason(raw: str) -> None:
    (row,) = _triage(_card("b", incident_date=raw, release_date="8/7/2026"))
    assert row["reason"] == f"incident_date present but not a resolvable date: {raw}"
    assert _RELEASE_ONLY not in str(row["reason"])
    assert row["available_dates"] == {
        "display_date": None,
        "incident_date": raw,
        "release_date": "8/7/2026",
    }


def test_unresolvable_display_date_is_named_in_the_reason() -> None:
    (row,) = _triage(_card("c", display_date="Undated", release_date="8/7/2026"))
    assert row["reason"] == "display_date present but not a resolvable date: Undated"


def test_release_date_only_reason_is_unchanged() -> None:
    (row,) = _triage(_card("d", release_date="5/8/2026"))
    assert _RELEASE_ONLY in str(row["reason"])


def test_no_date_reason_is_unchanged() -> None:
    (row,) = _triage(_card("e"))
    assert row["reason"] == _NO_DATE


def test_duplicate_card_ids_keep_their_own_outcome() -> None:
    cards = [
        _card("dup", incident_date="6/7/2024", release_date="5/8/2026"),
        _card("dup", incident_date="Undated", release_date="5/8/2026"),
        _card("dup", release_date="5/8/2026"),
    ]
    result = bucket({"cards": cards})
    assert [c.era for c in result.cards] == [
        Era.MODERN_OPERATIONAL,
        Era.UNDATED,
        Era.UNDATED,
    ]
    reasons = [row["reason"] for row in result.triage]
    assert len(reasons) == 2
    assert reasons[0] == "incident_date present but not a resolvable date: Undated"
    assert _RELEASE_ONLY in str(reasons[1])
