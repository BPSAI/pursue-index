"""Tests for era-year resolution over the display-date precedence (PV1.3).

The manifest's date fields are heterogeneous — bare years, ``M/D/YY``,
``M/D/YYYY``, ``Month, YYYY``, ranges and prose. :func:`parse_year` must pull
the earliest *defensible* era year and refuse to guess, and
:func:`resolve_era_date` must honour ``display_date`` → ``incident_date`` →
``release_date`` while recording which field it read.
"""

from __future__ import annotations

import pytest

from pursue_index.era_dates import ERA_PRECEDENCE, parse_year, resolve_era_date


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2025", 2025),
        ("1948", 1948),
        ("1970s", 1970),
        ("Late 2025", 2025),
        ("October, 2023", 2023),
        ("August 2 - September 2, 1965", 1965),
        ("1948-1950", 1948),  # range -> earliest
        ("1954-1974", 1954),
        ("3/22/49", 1949),  # M/D/YY, > pivot -> 19YY
        ("4/28/49", 1949),
        ("7/10/26", 2026),  # M/D/YY, <= pivot -> 20YY
        ("1/1/20", 2020),
        ("10/28/2001-10/29/2001", 2001),  # M/D/YYYY range
        ("1947-12-30", 1947),  # ISO
    ],
)
def test_parse_year_defensible(value: str, expected: int) -> None:
    assert parse_year(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "no year here", "n/a", "unknown"])
def test_parse_year_refuses_to_guess(value: object) -> None:
    assert parse_year(value) is None


def test_two_digit_pivot_boundary() -> None:
    assert parse_year("1/1/30") == 2030  # <= 30 -> 20YY
    assert parse_year("1/1/31") == 1931  # > 30 -> 19YY


def test_precedence_display_over_incident_over_release() -> None:
    card = {"display_date": "1999", "incident_date": "2025", "release_date": "7/10/26"}
    resolved = resolve_era_date(card)
    assert resolved.year == 1999
    assert resolved.source_field == "display_date"
    assert resolved.raw == "1999"


def test_precedence_falls_through_to_incident() -> None:
    card = {"display_date": None, "incident_date": "3/22/49", "release_date": "7/10/26"}
    resolved = resolve_era_date(card)
    assert resolved.year == 1949
    assert resolved.source_field == "incident_date"


def test_precedence_falls_through_to_release() -> None:
    card = {"display_date": None, "incident_date": None, "release_date": "7/10/26"}
    resolved = resolve_era_date(card)
    assert resolved.year == 2026
    assert resolved.source_field == "release_date"


def test_no_date_anywhere_resolves_to_none() -> None:
    resolved = resolve_era_date({"display_date": None, "incident_date": None, "release_date": None})
    assert resolved == (None, None, None)


def test_precedence_order_is_the_documented_one() -> None:
    assert ERA_PRECEDENCE == ("display_date", "incident_date", "release_date")
