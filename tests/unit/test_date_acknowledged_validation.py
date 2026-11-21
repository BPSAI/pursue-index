"""An overlay entry must be filled in, not pasted from the worklist template.

A field still holding a template placeholder (``<...>``) makes the entry
invalid, for both kinds; an acknowledged-unknown entry also needs an
``approved_at`` that parses as a timezone-aware ISO-8601 timestamp and an
``upstream_value`` in 2-digit-year ``M/D/YY`` form. An invalid entry is
ignored, so the row stays UNRESOLVED.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.scrape.date_resolutions import load_date_resolutions
from pursue_index.scrape.year_normalize import normalize_rows

_GOOD = {"card_id": "c1", "field": "incident_date", "value": None,
         "status": "acknowledged-unknown", "reason": "upstream year conflicts with the title",
         "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z",
         "upstream_value": "7/15/05"}
_TEMPLATE = {**_GOOD, "reason": "<why it stays unknown>", "curator": "<who>",
             "approved_at": "<ISO-8601 UTC>"}


def _load(tmp_path: Path, *rows: dict) -> dict:
    path = tmp_path / "date_resolutions.json"
    path.write_text(json.dumps({"entries": list(rows)}), encoding="utf-8")
    return load_date_resolutions(path)


def _row() -> dict:
    return {"card_id": "c1", "title": "Case", "asset_filename": None, "release_date": None,
            "incident_date": "7/15/05", "display_date": None, "raw": {}}


def test_pasted_template_is_ignored_and_the_row_stays_unresolved(tmp_path: Path) -> None:
    overlay = _load(tmp_path, _TEMPLATE)
    assert overlay == {}
    _, report = normalize_rows([_row()], [], 2026, overlay=overlay)
    assert report.acknowledged == [] and len(report.unresolved) == 1


@pytest.mark.parametrize("key", ["reason", "curator", "approved_at", "upstream_value"])
def test_any_placeholder_field_is_invalid(tmp_path: Path, key: str) -> None:
    assert _load(tmp_path, {**_GOOD, key: " <fill me> "}) == {}


@pytest.mark.parametrize("stamp", ["2026-11-21", "yesterday", "2026-11-21T00:00:00",
                                   "2026-13-01T00:00:00Z"])
def test_bad_approved_at_is_invalid(tmp_path: Path, stamp: str) -> None:
    assert _load(tmp_path, {**_GOOD, "approved_at": stamp}) == {}


@pytest.mark.parametrize("upstream", ["7/15/2005", "M/D/YY", "7-15-05", "15/7"])
def test_upstream_value_must_be_a_two_digit_year_date(tmp_path: Path, upstream: str) -> None:
    assert _load(tmp_path, {**_GOOD, "upstream_value": upstream}) == {}


def test_good_entry_still_clears_the_stop(tmp_path: Path) -> None:
    overlay = _load(tmp_path, _GOOD, {**_GOOD, "card_id": "c2",
                                      "approved_at": "2026-11-21T00:00:00+00:00"})
    assert len(overlay) == 2
    _, report = normalize_rows([_row()], [], 2026, overlay=overlay)
    assert report.unresolved == [] and len(report.acknowledged) == 1


def test_value_entry_with_a_placeholder_is_invalid(tmp_path: Path) -> None:
    value = {"card_id": "c1", "field": "incident_date", "value": "7/15/2005",
             "curator": "a curator", "approved_at": "2026-11-21T00:00:00Z"}
    assert len(_load(tmp_path, value)) == 1
    assert _load(tmp_path, {**value, "curator": "<who>"}) == {}
    assert _load(tmp_path, {**value, "approved_at": "<ISO-8601 UTC>"}) == {}
