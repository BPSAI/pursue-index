"""The release-window rule: ``release_date`` only, after the stored value
and the row's display_date. A 2-digit ``M/D/YY`` with no other evidence
resolves to ``20YY`` when the earliest 4-digit release year in the prior
manifest <= 20YY <= the new manifest's fetch year."""

from __future__ import annotations

from pursue_index.scrape.year_normalize import normalize_rows
from pursue_index.scrape.year_resolve import Window


def _row(card_id: str = "n", **fields) -> dict:
    base = {"card_id": card_id, "title": "New doc", "asset_filename": None,
            "release_date": None, "incident_date": None, "display_date": None, "raw": {}}
    base.update(fields)
    return base


_PRIOR_2026 = [_row("old", release_date="5/8/2026")]


def test_window_hit_resolves_and_is_labelled() -> None:
    out, report = normalize_rows([_row(release_date="11/20/26")], _PRIOR_2026, 2026)
    assert out[0]["release_date"] == "11/20/2026"
    assert out[0]["raw"] == {"Release Date": "11/20/26"}
    assert report.window == Window(2026, 2026)
    assert report.window_rows == [{"card_id": "n", "title": "New doc", "field": "release_date",
                                   "raw": "11/20/26", "value": "11/20/2026",
                                   "evidence": "release-window"}]
    assert report.unresolved == []


def test_outside_window_stays_unresolved() -> None:
    out, report = normalize_rows([_row(release_date="11/20/19")], _PRIOR_2026, 2026)
    assert out[0]["release_date"] is None
    assert [u["reason"] for u in report.unresolved] == ["outside_release_window"]
    assert report.window == Window(2026, 2026)
    assert report.window_rows == []


def test_no_four_digit_prior_release_date_means_no_window() -> None:
    prior = [_row("old", release_date="June, 2026", incident_date="1/18/1957")]
    out, report = normalize_rows([_row(release_date="11/20/26")], prior, 2026)
    assert out[0]["release_date"] is None
    assert [u["reason"] for u in report.unresolved] == ["no_century_evidence"]
    assert report.window is None


def test_incident_date_never_uses_the_window() -> None:
    prior = [_row("old", release_date="5/8/2026", incident_date="1/18/1957")]
    out, report = normalize_rows([_row(incident_date="11/20/26")], prior, 2026)
    assert out[0]["incident_date"] is None
    assert [u["reason"] for u in report.unresolved] == ["no_century_evidence"]
    assert report.window is None


def test_stored_value_beats_the_window() -> None:
    prior = [*_PRIOR_2026, _row("x", release_date="11/20/1926")]
    out, report = normalize_rows([_row("x", release_date="11/20/26")], prior, 2026)
    assert out[0]["release_date"] == "11/20/1926"
    assert report.window_rows == []


def test_display_date_beats_the_window() -> None:
    row = _row(release_date="11/20/26", display_date="1926-11-20")
    out, report = normalize_rows([row], _PRIOR_2026, 2026)
    assert out[0]["release_date"] == "11/20/1926"
    assert report.window_rows == []
