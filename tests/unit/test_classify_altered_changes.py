"""Tests for ``scripts/classify_altered_changes.py``.

The classifier categorizes each altered card by comparing the PDF
text layer of the pre-edit vs current bytes. Tests pin the helper
behaviors that don't require a real PDF (normalization + the
control-flow branches in classify_card).

End-to-end testing against real PDFs lives in the script's runtime
output (``data/altered-classification.json``); these tests guard
the boundary conditions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import classify_altered_changes as cac  # noqa: E402


# --------------------------- normalize_text ------------------------------


def test_normalize_text_collapses_whitespace_to_single_space() -> None:
    assert cac.normalize_text("foo   \n\tbar\n\n baz") == "foo bar baz"


def test_normalize_text_strips_leading_trailing_whitespace() -> None:
    assert cac.normalize_text("\n  hello world  \n") == "hello world"


def test_normalize_text_empty_returns_empty() -> None:
    assert cac.normalize_text("") == ""
    assert cac.normalize_text("   \n  \t  ") == ""


def test_normalize_text_collapses_unicode_whitespace() -> None:
    # NBSP, em-space, and similar should all collapse to a single space.
    assert cac.normalize_text("foo  bar") == "foo bar"


# --------------------------- classify_card -------------------------------


def test_classify_card_returns_none_for_single_entry() -> None:
    """Cards with a single byte-history entry aren't altered; the
    classifier shouldn't be called on them, but it's defensive."""
    assert cac.classify_card(
        card_id="abc", entries=[{"byte_sha256": "x", "archive_key": "archive/x.pdf"}],
        archive_dir=Path("/nonexistent"),
    ) is None


def test_classify_card_returns_none_for_empty_entries() -> None:
    assert cac.classify_card(
        card_id="abc", entries=[], archive_dir=Path("/nonexistent"),
    ) is None


def test_classify_card_marks_mp4_oldest_as_asset_type_change() -> None:
    """Upstream swapped video → PDF; no text-layer comparison meaningful."""
    result = cac.classify_card(
        card_id="abc",
        entries=[
            {"byte_sha256": "newpdf", "archive_key": "archive/newpdf.pdf"},
            {"byte_sha256": "oldmp4", "archive_key": "archive/oldmp4.mp4"},
        ],
        archive_dir=Path("/nonexistent"),
    )
    assert result is not None
    assert result["class"] == "asset_type_change"
    assert result["pre_archive_key"].endswith(".mp4")
    assert result["post_archive_key"].endswith(".pdf")


def test_classify_card_marks_missing_bytes_as_no_text_layer(
    tmp_path: Path,
) -> None:
    """If a PDF claimed by byte-history isn't on disk, we can't compare;
    don't crash, return no_text_layer with a diagnostic note."""
    result = cac.classify_card(
        card_id="abc",
        entries=[
            {"byte_sha256": "aaa", "archive_key": "archive/aaa.pdf"},
            {"byte_sha256": "bbb", "archive_key": "archive/bbb.pdf"},
        ],
        archive_dir=tmp_path,
    )
    assert result is not None
    assert result["class"] == "no_text_layer"
    assert "missing on disk" in result["note"]


# --------------------------- main / output shape -------------------------


def test_main_writes_counts_and_cards_to_output(tmp_path: Path) -> None:
    """The output JSON has _meta.counts + cards keys; downstream
    (`build_altered_diffs.py`) depends on that shape."""
    bh = tmp_path / "byte-history.json"
    bh.write_text("{}")  # empty: no altered cards
    out = tmp_path / "out.json"
    rc = cac.main([
        "--byte-history", str(bh),
        "--archive-dir", str(tmp_path),
        "--out", str(out),
    ])
    assert rc == 0
    import json
    data = json.loads(out.read_text())
    assert "_meta" in data
    assert "counts" in data["_meta"]
    assert "cards" in data
    assert isinstance(data["cards"], dict)
    # Every class should be a key in counts (set explicitly in main()):
    assert set(data["_meta"]["counts"].keys()) >= {
        "presentation_only", "content_changed", "no_text_layer",
        "asset_type_change",
    }
