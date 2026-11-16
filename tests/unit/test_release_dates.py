"""Release dates compare by the day they name, so M/D/YY matches M/D/YYYY."""

from __future__ import annotations

from datetime import date

from pursue_index.release_dates import parse_release_date, same_release_date


def test_both_year_widths_name_the_same_day() -> None:
    assert parse_release_date("6/12/26") == parse_release_date("6/12/2026") == date(2026, 6, 12)
    assert same_release_date("6/12/2026", "6/12/26")
    assert same_release_date("06/12/26", "6/12/2026")


def test_a_different_day_does_not_match() -> None:
    assert not same_release_date("6/12/2026", "6/13/26")


def test_unparseable_values_compare_exactly() -> None:
    assert parse_release_date("2026-06-12") is None
    assert parse_release_date("2/30/26") is None  # no such day
    assert same_release_date("2026-06-12", "2026-06-12")
    assert not same_release_date("2026-06-12", "6/12/26")
    assert not same_release_date(None, "6/12/26")
