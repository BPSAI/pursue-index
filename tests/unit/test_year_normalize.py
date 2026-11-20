"""2-digit-year normalization for EXISTING rows.

Upstream's CSV bae7455d switched raw ``Release Date`` / ``Incident Date``
from ``1/18/1957`` to ``1/18/57``. For a card_id already in the prior
manifest, the 4-digit value stored there is restored -- a lookup by row
identity, never a guess at the century.
"""

from __future__ import annotations

from pursue_index.scrape.year_normalize import normalize_rows


def _row(card_id: str = "c1", **fields) -> dict:
    base = {"card_id": card_id, "title": "Some title", "asset_filename": None,
            "release_date": None, "incident_date": None, "display_date": None, "raw": {}}
    base.update(fields)
    return base


def _flag(card_id: str, fld: str, raw: str, reason: str, title: str = "Some title") -> dict:
    return {"card_id": card_id, "title": title, "field": fld, "raw": raw, "reason": reason}


def test_existing_incident_date_restored_from_prior() -> None:
    prior = [_row(incident_date="1/18/1957")]
    out, report = normalize_rows([_row(incident_date="1/18/57")], prior)
    assert out[0]["incident_date"] == "1/18/1957"
    assert report.unresolved == []


def test_existing_release_date_restored_from_prior() -> None:
    prior = [_row(release_date="10/23/2026")]
    out, report = normalize_rows([_row(release_date="10/23/26")], prior)
    assert out[0]["release_date"] == "10/23/2026"
    assert report.unresolved == []


def test_restored_row_keeps_upstream_string_in_raw() -> None:
    prior = [_row(incident_date="1/18/1957")]
    out, _ = normalize_rows([_row(incident_date="1/18/57", raw={"Column1": ""})], prior)
    assert out[0]["raw"] == {"Column1": "", "Incident Date": "1/18/57"}


def test_rerun_on_normalized_rows_reproduces_rows_and_report() -> None:
    prior = [_row(release_date="1/1/2020")]
    new = [_row(release_date="10/23/2026"), _row("n", release_date="11/20/26")]
    once, first = normalize_rows(new, prior, 2026)
    twice, second = normalize_rows(once, prior, 2026)
    assert twice == once
    assert second == first


def test_stored_value_with_other_day_is_unresolved_not_restored() -> None:
    prior = [_row(incident_date="1/19/1957")]
    out, report = normalize_rows([_row(incident_date="1/18/57")], prior)
    assert out[0]["incident_date"] == "1/18/57"
    assert report.unresolved == [_flag("c1", "incident_date", "1/18/57", "prior_mismatch")]


def test_stored_value_with_other_month_or_year_is_unresolved() -> None:
    prior = [_row("a", incident_date="2/18/1957"), _row("b", incident_date="1/18/1958")]
    new = [_row("a", incident_date="1/18/57"), _row("b", incident_date="1/18/57")]
    out, report = normalize_rows(new, prior)
    assert [r["incident_date"] for r in out] == ["1/18/57", "1/18/57"]
    assert [u["reason"] for u in report.unresolved] == ["prior_mismatch", "prior_mismatch"]


def test_duplicate_card_id_group_that_agrees_is_restored() -> None:
    prior = [_row(incident_date="5/6/2022"), _row(incident_date="5/6/2022"),
             _row(incident_date=None)]
    new = [_row(incident_date="5/6/22"), _row(incident_date="5/6/22"), _row(incident_date=None)]
    out, report = normalize_rows(new, prior)
    assert [r["incident_date"] for r in out] == ["5/6/2022", "5/6/2022", None]
    assert report.unresolved == []


def test_duplicate_card_id_group_that_disagrees_is_unresolved() -> None:
    prior = [_row(incident_date="5/6/2022"), _row(incident_date="5/6/1922")]
    out, report = normalize_rows([_row(incident_date="5/6/22")], prior)
    assert out[0]["incident_date"] == "5/6/22"
    assert report.unresolved == [_flag("c1", "incident_date", "5/6/22", "prior_disagree")]


def test_four_digit_and_empty_values_pass_through() -> None:
    prior = [_row(incident_date="1/18/1957", release_date="10/23/2026")]
    new = [_row(incident_date="1/18/1957", release_date=None),
           _row("n", incident_date="", release_date="June, 2026")]
    out, report = normalize_rows(new, prior)
    assert out == new
    assert report.unresolved == []
    assert report.considered is False


def test_display_fields_untouched() -> None:
    prior = [_row(incident_date="1/18/1957", display_date="1957-01-18",
                  manifest_incident_date_raw="1/18/1957")]
    new = [_row(incident_date="1/18/57", display_date="1957-01-18",
                manifest_incident_date_raw="1/18/57")]
    out, _ = normalize_rows(new, prior)
    assert out[0]["display_date"] == "1957-01-18"
    assert out[0]["manifest_incident_date_raw"] == "1/18/57"


def test_input_rows_are_not_mutated() -> None:
    new = [_row(incident_date="1/18/57")]
    normalize_rows(new, [_row(incident_date="1/18/1957")])
    assert new[0]["incident_date"] == "1/18/57"
    assert new[0]["raw"] == {}


def test_two_digit_era_prior_passes_through_unflagged_and_is_counted() -> None:
    """Before 92b3 every snapshot carried 2-digit years: with no 4-digit
    precedent in the prior for a field there is no convention to restore,
    so values pass through unflagged -- and are counted."""
    prior = [_row("a", incident_date="1/18/57", release_date="10/23/26")]
    new = [_row("a", incident_date="1/18/57", release_date="10/23/26"),
           _row("b", incident_date="2/2/60", release_date="10/23/26")]
    out, report = normalize_rows(new, prior, 2026)
    assert out == new
    assert report.unresolved == []
    assert (report.considered, report.passed_through) == (True, 4)


def test_mixed_prior_still_normalizes() -> None:
    """A prior with any 4-digit date for the field (e.g. one carrying a few
    rows left unresolved by an earlier tranche) is in the 4-digit era."""
    prior = [_row("a", incident_date="1/18/1957"), _row("b", incident_date="2/2/60")]
    new = [_row("a", incident_date="1/18/57"), _row("b", incident_date="2/2/60")]
    out, report = normalize_rows(new, prior)
    assert out[0]["incident_date"] == "1/18/1957"
    assert report.unresolved == [_flag("b", "incident_date", "2/2/60", "prior_mismatch")]
    assert report.passed_through == 0
