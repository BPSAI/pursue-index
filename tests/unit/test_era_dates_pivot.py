"""Tests for the two-digit-year pivot guard (PV1.3, spec §4a/§5).

``M/D/YY`` carries no century. Expanding ``/29`` to 2029 rather than 1929 is a
convention, not evidence, and the 2015+ side of that convention is exactly the
bucket that emits ``no_prior_release_found``. So a pivot-derived year must never
be *sufficient* to reach the modern-operational era: it establishes a year only
when a four-digit year elsewhere on the same card says the same thing.
"""

from __future__ import annotations

import pytest

from pursue_index.era_dates import parse_year, parse_year_detail, resolve_era_date


@pytest.mark.parametrize("value", ["5/6/29", "1/1/30", "12/25/28", "7/10/26", "1/1/20"])
def test_bare_pivot_year_does_not_establish_a_modern_year(value: str) -> None:
    """A two-digit year alone never establishes a 2015+ year."""
    assert parse_year(value) is None


@pytest.mark.parametrize("value,expected", [("3/22/49", 1949), ("4/28/49", 1949), ("1/1/31", 1931)])
def test_pivot_below_the_modern_floor_still_parses(value: str, expected: int) -> None:
    """Pre-2015 pivot years are unaffected — they reach no negative-emitting era."""
    assert parse_year(value) == expected


def test_pivot_detail_reports_the_year_and_that_it_was_pivoted() -> None:
    detail = parse_year_detail("5/6/29")
    assert detail.year == 2029
    assert detail.pivot_derived is True


def test_four_digit_year_is_never_pivot_derived() -> None:
    detail = parse_year_detail("October, 2023")
    assert detail.year == 2023
    assert detail.pivot_derived is False


def test_modern_pivot_needs_a_four_digit_year_on_the_card() -> None:
    """An uncorroborated 2015+ pivot leaves the card undated, not modern."""
    card = {
        "title": "DOW-UAP-D027, Mission Report, United Arab Emirates, October 2023",
        "incident_date": "6/7/24",
        "release_date": None,
    }
    resolved = resolve_era_date(card)
    assert resolved.year is None
    assert resolved.source_field is None


def test_modern_pivot_is_accepted_when_the_card_corroborates_it() -> None:
    """A four-digit year elsewhere on the card turns the pivot into evidence."""
    card = {
        "title": "DOE-UAP-D005, Pantex Unidentified Object Incident Report, 2015",
        "incident_date": "9/1/15",
        "release_date": "7/10/26",
    }
    resolved = resolve_era_date(card)
    assert resolved.year == 2015
    assert resolved.source_field == "incident_date"
    assert resolved.raw == "9/1/15"


def test_release_date_never_corroborates_a_pivot() -> None:
    """``release_date`` is a publication date (≈2026 for every card), not evidence.

    Its 2026 must not license ``3/23/26`` on ``incident_date``: the card falls
    through to ``release_date`` itself, which carries no document era.
    """
    card = {"title": "Mission Report", "incident_date": "3/23/26", "release_date": "5/22/2026"}
    resolved = resolve_era_date(card)
    assert resolved.source_field == "release_date"
    assert resolved.source_field not in ("display_date", "incident_date")


def test_corroboration_must_match_the_pivoted_year() -> None:
    """A different four-digit year on the card does not license the pivot."""
    card = {"title": "Email Correspondence, Pacific Time Zone, March 2023", "incident_date": "3/23/26"}
    resolved = resolve_era_date(card)
    assert resolved.year is None
