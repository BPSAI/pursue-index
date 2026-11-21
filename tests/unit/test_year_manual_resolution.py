"""Row-level rules for open 2-digit-year items and the manual overlay.

* An UNRESOLVED field is left empty; upstream's string stays in ``raw``
  and a marker in ``raw`` records the open item.
* A prior row with an empty field, a marker and the same upstream value
  carries the item (``open``) instead of flagging it again.
* A field whose prior holds a 4-digit value keeps that stored value
  unchanged while UNRESOLVED (marked all the same), so no field change.
* A manual overlay entry is the highest-precedence evidence (``manual``),
  honoured only when its month, day and 2-digit year match upstream's.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.scrape.date_resolutions import load_date_resolutions
from pursue_index.scrape.year_normalize import normalize_rows
from pursue_index.tranche import field_diff

_M = "_date_unresolved"


def _row(card_id: str = "c1", **fields) -> dict:
    base = {"card_id": card_id, "title": "Some title", "asset_filename": None,
            "release_date": None, "incident_date": None, "display_date": None, "raw": {}}
    base.update(fields)
    return base


def _marker(raw: str = "1/18/57", reason: str = "no_century_evidence",
            tranche: str = "t0", at: str = "2026-11-01T00:00:00Z") -> dict:
    return {"field": "incident_date", "raw": raw, "reason": reason,
            "first_flagged_in": tranche, "first_flagged_at": at}


def _open_prior(card_id: str = "c1", **fields) -> dict:
    return _row(card_id, raw={"Incident Date": "1/18/57", _M: [_marker()]}, **fields)


def _manual(value: str, card_id: str = "c1") -> dict:
    return {(card_id, "incident_date"): {"value": value, "curator": "operator",
                                         "approved_at": "2026-11-20T00:00:00Z"}}


def test_unresolved_field_is_emptied_and_marked() -> None:
    out, report = normalize_rows([_row(incident_date="1/18/57")], [], 2026,
                                 tranche="t1", fetched_at="2026-11-20T00:00:00Z")
    assert out[0]["incident_date"] is None
    assert out[0]["raw"] == {"Incident Date": "1/18/57", _M: [
        _marker(tranche="t1", at="2026-11-20T00:00:00Z")]}
    assert len(report.unresolved) == 1 and report.open == []


def test_open_item_with_same_raw_is_carried_not_reflagged() -> None:
    out, report = normalize_rows([_row(incident_date="1/18/57")], [_open_prior()], 2026,
                                 tranche="t1", fetched_at="2026-11-20T00:00:00Z")
    assert report.unresolved == []
    assert report.open == [{"card_id": "c1", "title": "Some title", "field": "incident_date",
                            "raw": "1/18/57", "reason": "no_century_evidence",
                            "first_flagged_in": "t0",
                            "first_flagged_at": "2026-11-01T00:00:00Z"}]
    assert out[0]["incident_date"] is None and out[0]["raw"][_M] == [_marker()]


def test_emptied_field_is_never_passed_through() -> None:
    """The prior holds incident_date only in 2-digit form elsewhere (the
    field-level passthrough), but an emptied, marked field is still open."""
    prior = [_row("a", incident_date="2/2/60"), _open_prior("b")]
    new = [_row("a", incident_date="2/2/60"), _row("b", incident_date="1/18/57")]
    out, report = normalize_rows(new, prior, 2026)
    assert out[0]["incident_date"] == "2/2/60"
    assert report.passed_through == 1
    assert [o["card_id"] for o in report.open] == ["b"] and report.unresolved == []
    assert out[1]["incident_date"] is None


def test_manual_entry_is_highest_precedence() -> None:
    prior = [_row(incident_date="1/18/2057")]  # a stored value that would win otherwise
    out, report = normalize_rows([_row(incident_date="1/18/57")], prior, 2026,
                                 overlay=_manual("1/18/1957"))
    assert out[0]["incident_date"] == "1/18/1957"
    assert [(m["evidence"], m["value"], m["curator"]) for m in report.manual_rows] == [
        ("manual", "1/18/1957", "operator")]
    assert report.unresolved == []


def test_manual_entry_clears_the_marker() -> None:
    out, report = normalize_rows([_row(incident_date="1/18/57")], [_open_prior()], 2026,
                                 overlay=_manual("1/18/1957"))
    assert out[0]["incident_date"] == "1/18/1957"
    assert out[0]["raw"] == {"Incident Date": "1/18/57"}
    assert report.open == [] and report.unresolved == []


def test_manual_entry_that_mismatches_stays_unresolved() -> None:
    for value in ("1/19/1957", "2/18/1957", "1/18/1958", "1957"):
        out, report = normalize_rows([_row(incident_date="1/18/57")], [], 2026,
                                     overlay=_manual(value))
        assert out[0]["incident_date"] is None, value
        assert [u["reason"] for u in report.unresolved] == ["manual_mismatch"], value
        assert report.manual_rows == []


def test_rerun_on_normalized_rows_with_markers_reproduces() -> None:
    prior = [_row("p", release_date="1/1/2020")]
    new = [_row("n", incident_date="1/18/57"), _row("w", release_date="11/20/26")]
    kw = {"tranche": "t1", "fetched_at": "2026-11-20T00:00:00Z"}
    once, first = normalize_rows(new, prior, 2026, **kw)
    twice, second = normalize_rows(once, prior, 2026, **kw)
    assert twice == once and second == first


def test_overlay_loader(tmp_path: Path) -> None:
    path = tmp_path / "date_resolutions.json"
    assert load_date_resolutions(path) == {}
    path.write_text(json.dumps({"entries": [
        {"card_id": "c1", "field": "incident_date", "value": "1/18/1957",
         "curator": "operator", "approved_at": "2026-11-20T00:00:00Z"},
        {"card_id": "c2", "field": "title", "value": "x"},
        {"field": "release_date", "value": "1/1/2026"},
        "junk"]}), encoding="utf-8")
    assert load_date_resolutions(path) == _manual("1/18/1957")
    path.write_text("{not json", encoding="utf-8")
    assert load_date_resolutions(path) == {}


def _dup(card_id: str, url: str, **fields) -> dict:
    return _row(card_id, asset_url=url, asset_type="PDF", **fields)


def test_disagreeing_group_keeps_each_cards_own_stored_value() -> None:
    prior = [_dup("g", "u1", incident_date="5/6/2022"), _dup("g", "u2", incident_date="5/6/1922")]
    new = [_dup("g", "u1", incident_date="5/6/22"), _dup("g", "u2", incident_date="5/6/22")]
    out, report = normalize_rows(new, prior, 2026, tranche="t1")
    assert [r["incident_date"] for r in out] == ["5/6/2022", "5/6/1922"]
    assert [u["reason"] for u in report.unresolved] == ["prior_disagree", "prior_disagree"]
    assert all(r["raw"][_M][0]["reason"] == "prior_disagree" for r in out)
    assert field_diff(prior, out) == []
    again, second = normalize_rows(new, out, 2026, tranche="t2")
    assert second.unresolved == [] and len(second.open) == 2
    assert [r["incident_date"] for r in again] == ["5/6/2022", "5/6/1922"]
    assert field_diff(out, again) == []


def test_mismatch_keeps_stored_value_and_manual_still_replaces_it() -> None:
    prior = [_row(incident_date="1/18/1957")]
    out, report = normalize_rows([_row(incident_date="1/18/58")], prior, 2026)
    assert out[0]["incident_date"] == "1/18/1957"
    assert [u["reason"] for u in report.unresolved] == ["prior_mismatch"]
    assert field_diff(prior, out) == []
    fixed, rep = normalize_rows([_row(incident_date="1/18/58")], out, 2026,
                                overlay=_manual("1/18/1958"))
    assert fixed[0]["incident_date"] == "1/18/1958" and _M not in fixed[0]["raw"]
    assert rep.unresolved == [] and rep.open == []
