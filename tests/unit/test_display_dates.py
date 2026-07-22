"""Tests for the display-date curated overlay.

The overlay file ``data/display_dates.json`` holds operator-approved
date entries per card_id. After CSV parsing, ``merge_display_dates``
applies the overlay to the parsed cards, preserving the original CSV
incident_date in ``manifest_incident_date_raw`` for audit.

Schema per row:

  card_id                          : str   — required
  display_date                     : str | null  — YYYY-MM-DD or YYYY
  display_date_range               : [start, end] | null  — ISO 8601
  display_date_evidence            : str | null  — verbatim source span
  display_date_evidence_card_ref   : str | null  — <card_id>#page-N
  display_date_curator             : str | null  — "operator-david" or "agent-sonnet-4-6"
  display_date_approved_at         : str | null  — ISO 8601 timestamp
  display_date_abstention          : str | null  — when display_date is null
"""

from __future__ import annotations

import json

import pytest

from pursue_index.scrape.csv_fetcher import parse_csv
from pursue_index.scrape.display_dates import (
    DisplayDateEntry,
    load_display_dates,
    merge_display_dates,
)
from pursue_index.scrape.types import CardMetadata


_SAMPLE_CSV = (
    "﻿Redaction,Release Date,Title,Type,Video Pairing,PDF Pairing,"
    "Description Blurb,DVIDS Video ID,Video Title,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image\r\n"
    "True,5/8/26,Case 0001,PDF,,,Brief.,,,FBI,10/31/2023,Roswell,"
    "https://www.war.gov/case_0001.pdf,\r\n"
    "True,5/8/26,Case 0002,PDF,,,Brief.,,,FBI,N/A,N/A,"
    "https://www.war.gov/case_0002.pdf,\r\n"
).encode("utf-8")


def _parsed_cards() -> list[CardMetadata]:
    return parse_csv(_SAMPLE_CSV)


# --- Overlay file loading ---


def test_load_display_dates_returns_empty_dict_when_file_absent(tmp_path):
    overlay = load_display_dates(tmp_path / "nope.json")
    assert overlay == {}


def test_load_display_dates_parses_well_formed_file(tmp_path):
    path = tmp_path / "display_dates.json"
    path.write_text(json.dumps({
        "entries": [
            {
                "card_id": "abc1234567890def",
                "display_date": "2023-10-24",
                "display_date_evidence": "MISREP DTG 240015:00ZOCT23, p1",
                "display_date_evidence_card_ref": "abc1234567890def#page-1",
                "display_date_curator": "operator-david",
                "display_date_approved_at": "2026-05-15T10:00:00Z",
            }
        ]
    }))
    overlay = load_display_dates(path)
    assert "abc1234567890def" in overlay
    entry = overlay["abc1234567890def"]
    assert isinstance(entry, DisplayDateEntry)
    assert entry.display_date == "2023-10-24"
    assert entry.display_date_evidence_card_ref == "abc1234567890def#page-1"


def test_load_display_dates_handles_abstention_entry(tmp_path):
    path = tmp_path / "display_dates.json"
    path.write_text(json.dumps({
        "entries": [
            {
                "card_id": "abc1234567890def",
                "display_date": None,
                "display_date_abstention": "FBI omnibus file covers 1947-1968; no single document date",
                "display_date_evidence": "FBI declassification stamp May 24, 2007",
                "display_date_curator": "operator-david",
                "display_date_approved_at": "2026-05-15T10:00:00Z",
            }
        ]
    }))
    overlay = load_display_dates(path)
    entry = overlay["abc1234567890def"]
    assert entry.display_date is None
    assert "1947-1968" in (entry.display_date_abstention or "")


# --- Merge into parsed cards ---


def test_merge_preserves_original_incident_date_as_raw():
    """When an overlay row applies, the original CSV incident_date
    must be preserved on the card as manifest_incident_date_raw so the
    audit trail survives the merge."""
    cards = _parsed_cards()
    overlay = {
        cards[0].card_id: DisplayDateEntry(
            card_id=cards[0].card_id,
            display_date="2023-10-24",
            display_date_evidence="MISREP DTG 240015:00ZOCT23",
            display_date_curator="operator-david",
            display_date_approved_at="2026-05-15T10:00:00Z",
        )
    }
    merged = merge_display_dates(cards, overlay)

    assert merged[0].display_date == "2023-10-24"
    # Original CSV incident_date is preserved
    assert merged[0].manifest_incident_date_raw == "10/31/2023"


def test_merge_leaves_cards_without_overlay_untouched():
    cards = _parsed_cards()
    # Only overlay the FIRST card; second card has no overlay row.
    overlay = {
        cards[0].card_id: DisplayDateEntry(
            card_id=cards[0].card_id,
            display_date="2023-10-24",
            display_date_curator="operator-david",
            display_date_approved_at="2026-05-15T10:00:00Z",
        )
    }
    merged = merge_display_dates(cards, overlay)

    # Second card untouched: no display_date set; no raw field set.
    assert merged[1].display_date is None
    assert merged[1].manifest_incident_date_raw is None


def test_merge_is_pure_returns_new_cards():
    """Merge must not mutate inputs in place — callers may reuse them."""
    cards = _parsed_cards()
    overlay = {
        cards[0].card_id: DisplayDateEntry(
            card_id=cards[0].card_id,
            display_date="2023-10-24",
        )
    }
    merge_display_dates(cards, overlay)
    # Original is still unmodified
    assert cards[0].display_date is None
    assert cards[0].manifest_incident_date_raw is None


def test_merge_applies_full_provenance_fields():
    cards = _parsed_cards()
    overlay = {
        cards[0].card_id: DisplayDateEntry(
            card_id=cards[0].card_id,
            display_date="2023-10-24",
            display_date_range=("2023-10-24", "2023-10-24"),
            display_date_evidence="MISREP DTG 240015:00ZOCT23, p1",
            display_date_evidence_card_ref=f"{cards[0].card_id}#page-1",
            display_date_curator="operator-david",
            display_date_approved_at="2026-05-15T10:00:00Z",
        )
    }
    merged = merge_display_dates(cards, overlay)
    c = merged[0]
    assert c.display_date == "2023-10-24"
    assert c.display_date_range == ("2023-10-24", "2023-10-24")
    assert c.display_date_evidence == "MISREP DTG 240015:00ZOCT23, p1"
    assert c.display_date_evidence_card_ref == f"{cards[0].card_id}#page-1"
    assert c.display_date_curator == "operator-david"


def test_merge_applies_abstention():
    cards = _parsed_cards()
    overlay = {
        cards[1].card_id: DisplayDateEntry(
            card_id=cards[1].card_id,
            display_date=None,
            display_date_abstention="No defensible date",
            display_date_evidence="Declassification stamp 2007",
        )
    }
    merged = merge_display_dates(cards, overlay)
    c = merged[1]
    assert c.display_date is None
    assert c.display_date_abstention == "No defensible date"


# --- Schema validation: bad rows are skipped, not crashed ---


def test_load_display_dates_skips_rows_missing_card_id(tmp_path):
    path = tmp_path / "display_dates.json"
    path.write_text(json.dumps({
        "entries": [
            {"display_date": "2023-10-24"},  # no card_id
            {"card_id": "abc1234567890def", "display_date": "2024-01-01"},
        ]
    }))
    overlay = load_display_dates(path)
    assert len(overlay) == 1
    assert "abc1234567890def" in overlay
