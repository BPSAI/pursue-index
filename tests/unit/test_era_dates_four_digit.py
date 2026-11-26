"""Tests for the corroboration guard once numeric dates carry four-digit years.

The upstream CSV moved numeric dates from ``M/D/YY`` to ``M/D/YYYY``. The wider
year is upstream's expansion, not a century the document states, so a card must
resolve to the same era whichever width the CSV writes. Each case below is run
in both forms.
"""

from __future__ import annotations

import pytest

from pursue_index.era_bucketing import classify_card
from pursue_index.era_dates import parse_year, parse_year_detail, resolve_era_date
from pursue_index.era_models import Era

# (title, two-digit incident_date, four-digit incident_date)
_CONTRADICTED = [
    ("DOW-UAP-D027, Mission Report, United Arab Emirates, October 2023", "6/7/24", "6/7/2024"),
    ("DOW-UAP-D042, Range Fouler Debrief, Arabian Gulf, 2023", "8/31/20", "8/31/2020"),
    ("DOW-UAP-D051, Email Correspondence, Pacific Time Zone, March 2023", "3/23/26", "3/23/2026"),
]


@pytest.mark.parametrize("title,short,long", _CONTRADICTED)
@pytest.mark.parametrize("width", ["short", "long"])
def test_title_contradicting_a_modern_numeric_date_leaves_the_card_undated(
    title: str, short: str, long: str, width: str
) -> None:
    incident = short if width == "short" else long
    release = "5/8/26" if width == "short" else "5/8/2026"
    card = {"card_id": "x", "title": title, "incident_date": incident, "release_date": release}
    assert resolve_era_date(card).source_field != "incident_date"
    assert classify_card(card).era is Era.UNDATED


@pytest.mark.parametrize("incident", ["9/1/15", "9/1/2015"])
def test_corroborated_modern_numeric_date_is_accepted_in_both_widths(incident: str) -> None:
    card = {
        "title": "DOE-UAP-D005, Pantex Unidentified Object Incident Report, 2015",
        "incident_date": incident,
        "release_date": "7/10/2026",
    }
    resolved = resolve_era_date(card)
    assert resolved == (2015, "incident_date", incident)
    assert classify_card(card).era is Era.MODERN_OPERATIONAL


@pytest.mark.parametrize("incident,year", [("3/22/49", 1949), ("3/22/1949", 1949), ("5/24/62", 1962)])
def test_pre_modern_numeric_dates_need_no_corroboration(incident: str, year: int) -> None:
    card = {"title": "Report", "incident_date": incident, "release_date": "5/8/2026"}
    assert resolve_era_date(card) == (year, "incident_date", incident)


def test_a_four_digit_incident_date_does_not_corroborate_itself() -> None:
    card = {"title": "Mission Report", "incident_date": "6/7/2024", "release_date": None}
    assert resolve_era_date(card) == (None, None, None)


@pytest.mark.parametrize("incident", ["October, 2023", "2025", "Late 2025", "June, 2026"])
def test_prose_and_bare_year_incident_dates_are_unchanged(incident: str) -> None:
    """Only the numeric M/D/Y form carries an upstream-supplied century."""
    card = {"title": "Mission Report", "incident_date": incident, "release_date": "5/8/2026"}
    assert resolve_era_date(card).source_field == "incident_date"


def test_release_date_four_digit_year_is_recorded_as_stated() -> None:
    """release_date is never a document era; its stated year is not guarded."""
    card = {"title": "Mission Report", "incident_date": None, "release_date": "5/8/2026"}
    resolved = resolve_era_date(card)
    assert resolved == (2026, "release_date", "5/8/2026")
    assert classify_card(card).era is Era.UNDATED


@pytest.mark.parametrize("value", ["5/24/2962", "5/24/2962 - 5/25/1962", "1/1/1800", "12/31/2100"])
def test_numeric_date_with_an_implausible_year_is_unparseable(value: str) -> None:
    assert parse_year_detail(value) == (None, False, False)
    assert parse_year(value) is None


def test_implausible_incident_date_falls_through_and_does_not_borrow_a_year() -> None:
    """The upstream ``5/24/2962`` (title: May 24, 1962) yields no incident year."""
    card = {
        "card_id": "6b12c3ddc6a96008",
        "title": "NASA-UAP-D013, Mercury Atlas 7, May 24, 1962",
        "incident_date": "5/24/2962",
        "release_date": "5/22/2026",
    }
    resolved = resolve_era_date(card)
    assert resolved.source_field == "release_date"
    assert classify_card(card).era is Era.UNDATED


def test_curated_display_date_wins_over_an_implausible_incident_date() -> None:
    card = {
        "title": "NASA-UAP-D013, Mercury Atlas 7, May 24, 1962",
        "display_date": "1962-05-24",
        "incident_date": "5/24/2962",
        "release_date": "5/22/2026",
    }
    assert resolve_era_date(card) == (1962, "display_date", "1962-05-24")
    assert classify_card(card).era is Era.PRE_1970


def test_full_year_is_not_read_from_inside_a_longer_number() -> None:
    assert parse_year("ref 120195") is None
    assert parse_year("1970s") == 1970


def test_slash_dated_flag() -> None:
    assert parse_year_detail("6/7/2024").slash_dated is True
    assert parse_year_detail("6/7/24").slash_dated is False
    assert parse_year_detail("October, 2023").slash_dated is False
