"""An undated_triage row must never contradict a populated document date.

A document date that is present but held undated keeps the card on the triage
list, and the reason states why (unresolvable, or an uncorroborated century)
instead of claiming only a release_date.
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


_UNCORROBORATED = (
    "{field} {raw} present but its century is uncorroborated "
    "(numeric M/D/YYYY year; no corroborating field); held undated"
)


def test_uncorroborated_slash_year_stays_undated_with_its_own_reason() -> None:
    card = _card("a", incident_date="6/7/2024", release_date="5/8/2026")
    card["title"] = "Mission Report 1987"
    result = bucket({"cards": [card]})
    assert result.cards[0].era is Era.UNDATED
    (row,) = result.triage
    assert row["reason"] == _UNCORROBORATED.format(field="incident_date", raw="6/7/2024")
    assert _RELEASE_ONLY not in str(row["reason"])


def test_uncorroborated_slash_year_with_a_title_naming_no_year() -> None:
    (row,) = _triage(_card("a2", incident_date="6/7/2024", release_date="5/8/2026"))
    assert row["reason"] == _UNCORROBORATED.format(field="incident_date", raw="6/7/2024")


def test_uncorroborated_display_date_names_display_date() -> None:
    (row,) = _triage(_card("a3", display_date="3/9/2022"))
    assert row["reason"] == _UNCORROBORATED.format(field="display_date", raw="3/9/2022")


def test_corroborated_slash_year_buckets_the_card() -> None:
    card = _card("a4", incident_date="6/7/2024", release_date="5/8/2026")
    card["title"] = "Mission Report 2024"
    result = bucket({"cards": [card]})
    assert result.triage == []
    assert result.cards[0].era is Era.MODERN_OPERATIONAL
    assert result.cards[0].year == 2024


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


def test_undated_rows_of_one_file_keep_their_own_reasons() -> None:
    # A dated row elsewhere does not date these: they share no file with it.
    cards = [
        {**_card("other", incident_date="6/7/2024", release_date="5/8/2026"), "title": "Report 2024"},
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
