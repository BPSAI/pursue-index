"""Trailing card-title qualifiers (year, tape, part, continued) and the UTC search date."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from pursue_index import ntrs_match, ntrs_source
from pursue_index.ntrs_match import normalize_query, title_matches
from pursue_index.ntrs_source import RESULT_POST_DATING, evaluate_card
from tests.support.ntrs_fakes import TODAY, card, sample

D008 = "NASA-UAP-D008, Apollo 12 Medical Debriefing - Tape 12, 1969"

ROW_KEY = "a0a0a0a0a0a0a012#0"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (D008, "Apollo 12 Medical Debriefing"),
        (
            "NASA-UAP-D031, Apollo 17 Crew Medical Debriefing (Continued), 1972",
            "Apollo 17 Crew Medical Debriefing",
        ),
        ("NASA-UAP-D040, Gemini 7 Audio Excerpt, 1962-1964", "Gemini 7 Audio Excerpt"),
        ("NASA-UAP-D040, Gemini 7 Audio Excerpt, 1962\N{EN DASH}1964", "Gemini 7 Audio Excerpt"),
        (
            "NASA-UAP-D041, Apollo 11 Technical Air-to-Ground Voice Transcription Part 2",
            "Apollo 11 Technical Air-to-Ground Voice Transcription",
        ),
        (
            "NASA-UAP-D041, Apollo 11 Voice Transcription - Part 3, 1969",
            "Apollo 11 Voice Transcription",
        ),
        (
            "NASA-UAP-D041, Apollo 11 Voice Transcription (Part 4), 1969",
            "Apollo 11 Voice Transcription",
        ),
        (
            "NASA-UAP-D041, Apollo 11 Voice Transcription (continued) - TAPE 7, 1969",
            "Apollo 11 Voice Transcription",
        ),
        ("NASA-UAP-D050, Apollo 16 Scientific Debriefing", "Apollo 16 Scientific Debriefing"),
    ],
)
def test_trailing_qualifiers_are_stripped_from_the_query(title: str, expected: str) -> None:
    assert normalize_query(title) == expected


def test_a_title_with_a_year_only_inside_it_is_unchanged() -> None:
    assert (
        normalize_query("NASA-UAP-D060, Report On 1969 Flights Summary")
        == "Report On 1969 Flights Summary"
    )


def test_d008_matches_the_real_sample_and_is_a_post_dating_copy_without_a_claim() -> None:
    result_title = sample()["results"][0]["title"]
    assert title_matches(D008, result_title)
    search = evaluate_card(card(title=D008, release_date="5/8/2026"), sample(), TODAY, ROW_KEY)
    assert search.result == RESULT_POST_DATING
    assert search.claim is None
    assert search.query == "Apollo 12 Medical Debriefing"
    assert len(search.copies) == 1


def test_strictness_is_unchanged_for_a_short_card_title() -> None:
    assert not title_matches("Apollo 12", "Apollo 12 Lunar Surface Journal Index")
    assert not title_matches(
        "NASA-UAP-D001, Apollo 12, 1969", "Apollo 12 Lunar Surface Journal Index"
    )


def test_a_year_on_the_result_title_is_not_a_free_match() -> None:
    # a result title carrying the year is an extra token, not a free match
    assert not title_matches(
        "Apollo 12 Medical Debriefing, 1969", "Apollo 12 Medical Debriefing 1969 Notes Extra"
    )


def test_the_search_date_is_the_utc_date_from_an_injected_clock() -> None:
    assert hasattr(ntrs_match, "utc_today")
    seen: list[Any] = []

    def clock(tz: Any) -> datetime:
        seen.append(tz)
        # 23:30 on the 25th in UTC-5 is already the 26th in UTC
        return datetime(2026, 11, 26, 4, 30, tzinfo=UTC).astimezone(tz)

    assert ntrs_match.utc_today(clock) == date(2026, 11, 26)
    assert seen == [UTC]


def test_main_searches_with_the_utc_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    got: list[date] = []
    monkeypatch.setattr(ntrs_source, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(ntrs_source, "load_ntrs_hosts", lambda root: frozenset({"ntrs.nasa.gov"}))
    monkeypatch.setattr(ntrs_source, "run", lambda root, fetcher, day: got.append(day) or 0)
    monkeypatch.setattr(ntrs_source, "utc_today", lambda: date(2026, 11, 26), raising=False)
    assert ntrs_source.main() == 0
    assert got == [date(2026, 11, 26)]
