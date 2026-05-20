"""Tests for CSV normalization helpers."""

from __future__ import annotations

import pytest

from pursue_index.scrape.normalize import (
    clean_str,
    clean_title,
    filename_from_url,
    normalize_asset_type,
    parse_redacted,
    stable_card_id,
)


def test_clean_str_treats_na_as_none() -> None:
    assert clean_str("N/A") is None
    assert clean_str(" n/a ") is None
    assert clean_str("") is None
    assert clean_str(None) is None
    assert clean_str("FBI") == "FBI"


def test_clean_title_collapses_newlines() -> None:
    raw = "\n65_HS1-834228961_62-HQ-83894_Section_10\n"
    assert clean_title(raw) == "65_HS1-834228961_62-HQ-83894_Section_10"


def test_normalize_asset_type_handles_trailing_space() -> None:
    # The CSV has 6 rows with "PDF " (trailing space).
    assert normalize_asset_type("PDF ") == "PDF"
    assert normalize_asset_type("pdf") == "PDF"
    assert normalize_asset_type("VID") == "VID"
    assert normalize_asset_type("img") == "IMG"


def test_normalize_asset_type_accepts_aud() -> None:
    """Sprint 4f: upstream relabeled the NASA Gemini 7 audio card
    (card_id 167f6a21c7238d0c) from VID → AUD between tranche
    c9cc83fcaf43 and f75e2f7de0ff. Parser must accept AUD as a
    first-class asset type — same DVIDS-hosted metadata-only
    semantics as VID, just audio instead of video.
    """
    assert normalize_asset_type("AUD") == "AUD"
    assert normalize_asset_type("aud") == "AUD"
    assert normalize_asset_type("AUD ") == "AUD"


def test_normalize_asset_type_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        normalize_asset_type("DOC")
    # PHOTO is plausibly close to IMG but isn't a canonical type —
    # must still fail closed so a future schema change surfaces loud.
    with pytest.raises(ValueError):
        normalize_asset_type("PHOTO")


def test_parse_redacted() -> None:
    assert parse_redacted("True") is True
    assert parse_redacted("true") is True
    assert parse_redacted("") is False
    assert parse_redacted(None) is False
    assert parse_redacted("False") is False  # CSV doesn't actually use False


def test_filename_from_url() -> None:
    url = "https://www.war.gov/medialink/ufo/release_1/65_hs1-834228961_62-hq-83894_section_10.pdf"
    assert filename_from_url(url) == "65_hs1-834228961_62-hq-83894_section_10.pdf"
    assert filename_from_url(None) is None


def test_stable_card_id_is_deterministic() -> None:
    a = stable_card_id("https://example.com/a.pdf", "Title A")
    b = stable_card_id("https://example.com/a.pdf", "Different title")
    c = stable_card_id("https://example.com/b.pdf", "Title A")
    assert a == b  # url drives the id
    assert a != c
    assert len(a) == 16
