"""2-digit-year normalization for NEW rows (no stored value), and the
CardMetadata entry point.

A new row's century comes only from the row's own 4-digit display_date,
or -- for incident_date only -- a 4-digit year in its title/filename.
Anything else is flagged and its field left empty, never guessed.
(The release-window rule for release_date is in test_year_release_window.)
"""

from __future__ import annotations

from datetime import UTC, datetime

from pursue_index.scrape.types import CardMetadata
from pursue_index.scrape.year_normalize import normalize_cards, normalize_rows


def _row(card_id: str = "new1", **fields) -> dict:
    base = {"card_id": card_id, "title": "Untitled memo", "asset_filename": None,
            "release_date": None, "incident_date": None, "display_date": None, "raw": {}}
    base.update(fields)
    return base


def test_new_row_without_evidence_is_emptied_and_unresolved() -> None:
    out, report = normalize_rows([_row(incident_date="1/18/57")], [])
    assert out[0]["incident_date"] is None
    assert report.unresolved == [{"card_id": "new1", "title": "Untitled memo",
                                  "field": "incident_date", "raw": "1/18/57",
                                  "reason": "no_century_evidence"}]


def test_new_row_display_date_supplies_century() -> None:
    rows = [_row(incident_date="1/18/57", display_date="1957-01-18"),
            _row("new2", incident_date="1/18/57", display_date="1/18/1957")]
    out, report = normalize_rows(rows, [])
    assert [r["incident_date"] for r in out] == ["1/18/1957", "1/18/1957"]
    assert report.unresolved == []


def test_new_row_display_date_that_disagrees_is_not_used() -> None:
    out, report = normalize_rows([_row(incident_date="1/18/57", display_date="1957-01-19")], [])
    assert out[0]["incident_date"] is None
    assert report.unresolved[0]["reason"] == "no_century_evidence"


def test_new_row_title_year_supplies_incident_century() -> None:
    title = "DOW-UAP-D182, AAWSAP Statement of Work, August 2008"
    out, report = normalize_rows([_row(title=title, incident_date="8/22/08")], [])
    assert out[0]["incident_date"] == "8/22/2008"
    assert out[0]["raw"] == {"Incident Date": "8/22/08"}
    assert report.unresolved == []


def test_new_row_filename_year_supplies_incident_century() -> None:
    row = _row(asset_filename="dow-uap-d182-memo-1957.pdf", incident_date="1/18/57")
    out, report = normalize_rows([row], [])
    assert out[0]["incident_date"] == "1/18/1957"
    assert report.unresolved == []


def test_title_year_is_never_used_for_release_date() -> None:
    title = "DOW-UAP-D182, AAWSAP Statement of Work, August 2008"
    out, report = normalize_rows([_row(title=title, release_date="10/23/08")], [])
    assert out[0]["release_date"] is None
    assert [(u["field"], u["reason"]) for u in report.unresolved] == [
        ("release_date", "no_century_evidence")]


def test_two_distinct_matching_title_years_are_unresolved() -> None:
    row = _row(title="Report 1908 and 2008 follow-up", incident_date="8/22/08")
    out, report = normalize_rows([row], [])
    assert out[0]["incident_date"] is None
    assert report.unresolved[0]["reason"] == "ambiguous_evidence"


def test_non_matching_title_year_is_ignored() -> None:
    row = _row(title="Report of 1952", incident_date="8/22/08")
    out, report = normalize_rows([row], [])
    assert out[0]["incident_date"] is None
    assert report.unresolved[0]["reason"] == "no_century_evidence"


def test_existing_card_with_no_stored_value_uses_new_row_path() -> None:
    prior = [_row(incident_date=None)]
    title = "AAWSAP Statement of Work, August 2008"
    out, report = normalize_rows([_row(title=title, incident_date="8/22/08")], prior)
    assert out[0]["incident_date"] == "8/22/2008"
    assert report.unresolved == []


def _card(card_id: str, **fields) -> CardMetadata:
    return CardMetadata(card_id=card_id, title=fields.pop("title", "T"), asset_type="PDF",
                        agency="DOW", **fields)


def test_normalize_cards_restores_and_flags() -> None:
    prior = [_card("a", incident_date="1/18/1957", release_date="10/23/2026")]
    new = [_card("a", incident_date="1/18/57", release_date="10/23/26",
                 raw={"Column1": ""}),
           _card("b", incident_date="1/18/57", release_date="11/20/26")]
    out, report = normalize_cards(new, prior, datetime(2026, 11, 20, tzinfo=UTC))
    assert (out[0].incident_date, out[0].release_date) == ("1/18/1957", "10/23/2026")
    assert out[0].raw == {"Column1": "", "Release Date": "10/23/26", "Incident Date": "1/18/57"}
    assert (out[1].incident_date, out[1].release_date) == (None, "11/20/2026")
    assert report.unresolved == [{"card_id": "b", "title": "T", "field": "incident_date",
                                  "raw": "1/18/57", "reason": "no_century_evidence"}]
    assert new[0].incident_date == "1/18/57"
