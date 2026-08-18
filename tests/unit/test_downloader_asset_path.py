"""Tests for ``pursue_index.download.downloader.asset_path_for``.

Locks the fail-closed contract for unknown / no-bytes
asset types — added alongside AUD support so the next new asset
type (whatever upstream introduces next) also degrades safely
without KeyErroring through the pipeline.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import CardMetadata


def _card(**overrides) -> CardMetadata:
    """Minimal card with overridable fields. ``model_config`` allows
    re-validation per field; bypass that by constructing via
    ``model_construct`` so tests can set ``asset_type`` to a value
    that's outside the canonical Literal set (the future-unknown
    case)."""
    defaults = {
        "card_id": "abc1234567890def",
        "title": "Test card",
        "asset_type": "PDF",
        "agency": "Test",
        "redacted": False,
    }
    defaults.update(overrides)
    return CardMetadata.model_construct(**defaults)


def test_asset_path_for_pdf_returns_pdf_dir_path() -> None:
    card = _card(
        asset_type="PDF",
        asset_url="https://war.gov/x.pdf",
        asset_filename="x.pdf",
    )
    path = asset_path_for(card)
    assert path is not None
    assert path.name == "x.pdf"
    assert "abc1234567890def" in str(path)


def test_asset_path_for_aud_returns_none() -> None:
    """AUD cards are DVIDS-hosted with no asset_url; the no-url
    short-circuit returns None before we ever look up the type."""
    card = _card(asset_type="AUD", asset_url=None, asset_filename=None)
    assert asset_path_for(card) is None


def test_asset_path_for_aud_with_asset_url_still_returns_none() -> None:
    """Lock the ``.get()`` fail-closed
    path for AUD specifically. The prior AUD test only exercised the
    no-url short-circuit. If a future sprint adds an AUD card with
    asset_url + asset_filename (or upstream changes), the type→dir
    map must STILL return None until ``AUD`` is explicitly added
    with a real download target. Otherwise audio cards silently
    enter the PDF download lane with the wrong base dir.
    """
    card = _card(
        asset_type="AUD",
        asset_url="https://war.gov/audio.mp3",
        asset_filename="audio.mp3",
    )
    assert asset_path_for(card) is None


def test_asset_path_for_vid_returns_none_when_no_asset_url() -> None:
    """VID parity check — same DVIDS-hosted shape as AUD."""
    card = _card(asset_type="VID", asset_url=None, asset_filename=None)
    assert asset_path_for(card) is None


def test_asset_path_for_unknown_type_returns_none_not_keyerror() -> None:
    """Fail-closed posture. A future schema change that
    introduces (say) 'GLB' or 'WAV' must NOT KeyError through the
    pipeline before the parser is updated to know about it. ``.get()``
    on the type→dir map returns None for unknown types, which
    propagates as "skip this card" through every downstream
    consumer.
    """
    card = _card(
        asset_type="UNKNOWN_FUTURE_TYPE",  # bypasses Literal via model_construct
        asset_url="https://war.gov/x.bin",
        asset_filename="x.bin",
    )
    assert asset_path_for(card) is None


def test_asset_path_for_no_filename_returns_none() -> None:
    card = _card(
        asset_type="PDF",
        asset_url="https://war.gov/x.pdf",
        asset_filename=None,
    )
    assert asset_path_for(card) is None
