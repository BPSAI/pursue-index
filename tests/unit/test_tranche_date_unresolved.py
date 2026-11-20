"""The tranche-diff receipt and the tranche-ready record surface rows whose
2-digit year could not be restored, so the
operator sees them before approving."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tranche_diff  # noqa: E402

from pursue_index.release import rates  # noqa: E402
from pursue_index.tranche_ready.record import RecordInputs, build_record  # noqa: E402
from pursue_index.tranche_ready.schema import load_schema, validate  # noqa: E402
from pursue_index.tranche_report import render_markdown  # noqa: E402

SHA_OLD, SHA_NEW = "b" * 64, "a" * 64
_UNRESOLVED = {"card_id": "2" * 16, "title": "Report on lights", "field": "incident_date",
               "raw": "1/18/57", "reason": "no_century_evidence"}


def _card(card_id: str, **fields) -> dict:
    return {"card_id": card_id, "title": "T", "asset_type": "PDF", "asset_url": None,
            "asset_filename": None, "release_date": None, "incident_date": None,
            "raw": {}, **fields}


def _diff(new_cards: list[dict]) -> dict:
    old = {"csv_sha256": SHA_OLD, "cards": [_card("1" * 16, incident_date="1/18/1957"),
                                            _card("0" * 16, release_date="5/8/2026")]}
    keep = _card("0" * 16, release_date="5/8/2026")
    new = {"csv_sha256": SHA_NEW, "fetched_at": "2026-11-20T12:00:00Z",
           "cards": [keep, *new_cards]}
    return tranche_diff.diff_tranches(old, new, {}, fetch_byte_sha=lambda _url: None)


def test_receipt_restores_existing_rows_and_lists_unresolved() -> None:
    diff = _diff([_card("1" * 16, incident_date="1/18/57"),
                  _card("2" * 16, title="Report on lights", incident_date="1/18/57")])
    assert diff["field_only_changes"] == []
    assert diff["date_unresolved"] == [_UNRESOLVED]
    assert diff["summary"]["date_unresolved"] == 1


def test_receipt_omits_date_unresolved_when_none() -> None:
    diff = _diff([_card("1" * 16, incident_date="1/18/57")])
    assert "date_unresolved" not in diff
    assert "date_unresolved" not in diff["summary"]
    assert "Date unresolved" not in render_markdown(diff)


def test_markdown_worklist_has_labelled_section() -> None:
    md = render_markdown(_diff([_card("2" * 16, title="Report on lights",
                                      incident_date="1/18/57")]))
    assert "## Date unresolved (2-digit year left as upstream gave it — MANUAL REVIEW)" in md
    assert ("| `2222222222222222` | Report on lights | incident_date | `1/18/57` "
            "| no_century_evidence |") in md
    assert "- **1** dates unresolved" in md
    assert "- **0** 2-digit priors passed through" in md


def test_receipt_records_release_window_bounds_and_rows() -> None:
    diff = _diff([_card("3" * 16, title="New doc", release_date="11/20/26")])
    assert diff["release_window"] == {
        "lower": 2026, "upper": 2026,
        "source": "lower: earliest 4-digit release_date year in the prior manifest; "
                  "upper: year of the new manifest's fetched_at"}
    assert [(r["card_id"], r["value"], r["evidence"]) for r in diff["release_window_rows"]] == [
        ("3" * 16, "11/20/2026", "release-window")]
    assert diff["summary"]["release_window_resolved"] == 1
    assert "## Release window (2026-2026)" in render_markdown(diff)


def test_receipt_counts_two_digit_priors_passed_through() -> None:
    old = {"csv_sha256": SHA_OLD, "cards": [_card("1" * 16, release_date="5/8/26")]}
    new = {"csv_sha256": SHA_NEW, "cards": [_card("1" * 16, release_date="5/8/26"),
                                            _card("2" * 16, release_date="6/1/26")]}
    diff = tranche_diff.diff_tranches(old, new, {}, fetch_byte_sha=lambda _url: None)
    assert diff["summary"]["two_digit_priors_passed_through"] == 2
    assert "date_unresolved" not in diff
    assert "- **2** 2-digit priors passed through" in render_markdown(diff)


def _record_inputs(diff: dict) -> RecordInputs:
    return RecordInputs(
        old_manifest={"csv_sha256": SHA_OLD, "cards": []},
        new_manifest={"csv_sha256": SHA_NEW, "cards": []},
        diff=diff, candidates=[], page_counts={}, new_fallback_ids=[], old_fetched=0,
        old_failures=[], judge=rates.JudgeRate(0.0165, rates.JUDGE_METERED),
        tranche_issue=None, supersedes=[], generated_by={"tool": "t", "version": "v"},
        generated_at="2026-11-20T00:00:00+00:00",
    )


def test_record_stops_and_asks_on_unresolved_dates_and_validates() -> None:
    diff = {"summary": {}, "date_unresolved": [copy.deepcopy(_UNRESOLVED)]}
    record = build_record(_record_inputs(diff))
    assert record["status"] == "stop-and-ask"
    assert record["stop_reasons"] == [
        "2222222222222222 (Report on lights): date_unresolved incident_date '1/18/57' "
        "(no_century_evidence)"]
    assert validate(record, load_schema()) == []


def test_record_without_unresolved_dates_is_unchanged() -> None:
    record = build_record(_record_inputs({"summary": {}}))
    assert record["status"] == "ready"
    assert "stop_reasons" not in record


def test_tranche_ready_job_normalizes_the_manifest_it_builds_from_raw() -> None:
    from _tranche_ready_run import normalized_manifest

    raw = ("﻿Release Date,Title,Type,Agency,Incident Date,PDF | Image Link\r\n"
           '10/23/26,"Case 1",PDF,FBI,1/18/57,https://www.war.gov/medialink/c1.pdf\r\n'
           ).encode()
    first = normalized_manifest(raw, "https://www.war.gov/x.csv", {"cards": []})
    old = {"cards": [{**first.cards[0].model_dump(mode="json"),
                      "release_date": "10/23/2026", "incident_date": "1/18/1957"}]}
    card = normalized_manifest(raw, "https://www.war.gov/x.csv", old).cards[0]
    assert (card.release_date, card.incident_date) == ("10/23/2026", "1/18/1957")
