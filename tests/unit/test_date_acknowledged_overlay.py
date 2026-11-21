"""Loading acknowledged-unknown entries from the date-resolution overlay.

An acknowledged-unknown entry records that a 2-digit-year date stays
unknown: ``value`` is null (or absent), ``status`` is exactly
``acknowledged-unknown``, and ``reason``, ``curator``, ``approved_at`` and
``upstream_value`` (the exact upstream string acknowledged) are required.
Anything short of that is skipped like any other invalid row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.scrape.date_resolutions import load_date_resolutions

_ACK = {"card_id": "c1", "field": "incident_date", "value": None,
        "status": "acknowledged-unknown", "reason": "upstream year conflicts with the title",
        "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z", "upstream_value": "7/15/05"}


def _load(tmp_path: Path, *rows: dict) -> dict:
    path = tmp_path / "date_resolutions.json"
    path.write_text(json.dumps({"entries": list(rows)}), encoding="utf-8")
    return load_date_resolutions(path)


def test_acknowledged_entry_is_loaded(tmp_path: Path) -> None:
    assert _load(tmp_path, _ACK) == {("c1", "incident_date"): {
        "value": None, "status": "acknowledged-unknown",
        "reason": "upstream year conflicts with the title", "curator": "a curator",
        "approved_at": "2026-11-21T00:00:00Z", "upstream_value": "7/15/05"}}


def test_value_may_be_absent(tmp_path: Path) -> None:
    row = {k: v for k, v in _ACK.items() if k != "value"}
    assert _load(tmp_path, row)[("c1", "incident_date")]["status"] == "acknowledged-unknown"


@pytest.mark.parametrize("missing", ["reason", "curator", "approved_at", "upstream_value"])
def test_entry_missing_a_required_key_is_skipped(tmp_path: Path, missing: str) -> None:
    assert _load(tmp_path, {k: v for k, v in _ACK.items() if k != missing}) == {}
    assert _load(tmp_path, {**_ACK, missing: "  "}) == {}


def test_string_value_with_acknowledged_status_is_skipped(tmp_path: Path) -> None:
    assert _load(tmp_path, {**_ACK, "value": "7/15/2005"}) == {}


def test_null_value_without_the_exact_status_is_skipped(tmp_path: Path) -> None:
    assert _load(tmp_path, {**_ACK, "status": "acknowledged"}) == {}
    assert _load(tmp_path, {k: v for k, v in _ACK.items() if k != "status"}) == {}


def test_value_entries_load_as_before(tmp_path: Path) -> None:
    row = {"card_id": "c2", "field": "release_date", "value": " 1/18/1957 ",
           "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z"}
    assert _load(tmp_path, row, _ACK)[("c2", "release_date")] == {
        "value": "1/18/1957", "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z"}


def test_last_row_wins_across_kinds(tmp_path: Path) -> None:
    value = {"card_id": "c1", "field": "incident_date", "value": "7/15/2005",
             "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z"}
    assert _load(tmp_path, value, _ACK)[("c1", "incident_date")]["status"] == (
        "acknowledged-unknown")
    assert _load(tmp_path, _ACK, value)[("c1", "incident_date")]["value"] == "7/15/2005"


def test_every_acknowledged_field_is_part_of_the_digest(tmp_path: Path) -> None:
    from pursue_index.scrape.variants import overlay_digest

    cards = [{"card_id": "c1", "incident_date": "7/15/05", "raw": {}}]
    base = overlay_digest(_load(tmp_path, _ACK), cards)
    assert base is not None
    for key, other in (("reason", "another reason"), ("upstream_value", "7/16/05"),
                       ("curator", "another curator"), ("approved_at", "2026-11-22T00:00:00Z")):
        assert overlay_digest(_load(tmp_path, {**_ACK, key: other}), cards) != base, key
