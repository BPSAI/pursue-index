"""Tests for ``scripts/build_altered_diffs.py`` (Sprint 4h Phase 2).

Reads:
  * Pre-edit OCR: web/public/data/pages-cleaned.json (built 2026-05-12
    from the pre-overlay versions). Shape: {"pages": [{"card_id",
    "page", "text", "confidence"}, ...]}.
  * Post-edit OCR: data/altered-ocr/<card_id>/pages.jsonl (Phase 1
    output). One row per page: {"page", "text", "confidence",
    "byte_sha256"}.

Emits ``web/src/data/altered-diffs.json`` keyed card_id → diff result.
The diff is sentence-level (line-level is too noisy for OCR text;
paragraph-level loses redaction granularity).

Pure transform: no I/O in the helpers, no API. Tests pin algorithm
against synthetic before/after pairs covering the canonical redaction
patterns.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_altered_diffs as bad  # noqa: E402


# --------------------------- split_sentences -----------------------------


def test_split_sentences_basic() -> None:
    text = "First sentence. Second sentence. Third."
    assert bad.split_sentences(text) == [
        "First sentence.",
        "Second sentence.",
        "Third.",
    ]


def test_split_sentences_preserves_question_and_exclamation() -> None:
    text = "Hello? Yes! No."
    assert bad.split_sentences(text) == ["Hello?", "Yes!", "No."]


def test_split_sentences_handles_no_terminator() -> None:
    """OCR sometimes drops the final period. Treat as a single chunk."""
    assert bad.split_sentences("No terminator at all") == ["No terminator at all"]


def test_split_sentences_collapses_repeated_whitespace() -> None:
    assert bad.split_sentences("A.   B.\n\n  C.") == ["A.", "B.", "C."]


def test_split_sentences_skips_empty_blocks() -> None:
    assert bad.split_sentences("   \n\n  \t  ") == []


# --------------------------- diff_pages ----------------------------------


def test_diff_pages_pure_deletion() -> None:
    before = "Keep this sentence. Redact this one. Keep this too."
    after = "Keep this sentence. Keep this too."
    segments = bad.diff_sentences(before, after)
    kinds = [s["kind"] for s in segments]
    assert "removed" in kinds
    assert "added" not in kinds
    # The removed text is captured.
    removed = [s for s in segments if s["kind"] == "removed"]
    assert any("Redact this one" in s["text"] for s in removed)


def test_diff_pages_pure_addition() -> None:
    before = "Original sentence."
    after = "Original sentence. Added sentence here."
    segments = bad.diff_sentences(before, after)
    added = [s for s in segments if s["kind"] == "added"]
    assert any("Added sentence" in s["text"] for s in added)


def test_diff_pages_identical_inputs_are_all_equal_segments() -> None:
    text = "A sentence. Another sentence."
    segments = bad.diff_sentences(text, text)
    # All segments should be "equal" — no removed, no added.
    assert all(s["kind"] == "equal" for s in segments)


def test_diff_pages_empty_before_treats_all_as_added() -> None:
    segments = bad.diff_sentences("", "New text appears.")
    assert any(s["kind"] == "added" for s in segments)
    assert all(s["kind"] != "removed" for s in segments)


def test_diff_pages_empty_after_treats_all_as_removed() -> None:
    segments = bad.diff_sentences("Original text.", "")
    assert any(s["kind"] == "removed" for s in segments)
    assert all(s["kind"] != "added" for s in segments)


# --------------------------- summarize_diff ------------------------------


def test_summarize_diff_counts_word_deltas() -> None:
    segments = [
        {"kind": "equal", "text": "Keep this."},
        {"kind": "removed", "text": "Redact ten secret words here please now go."},
        {"kind": "added", "text": "Three new words."},
    ]
    summary = bad.summarize_diff(segments)
    # 8 words: Redact, ten, secret, words, here, please, now, go.
    assert summary["removed_words"] == 8
    assert summary["added_words"] == 3


def test_summarize_diff_zero_for_all_equal() -> None:
    segments = [{"kind": "equal", "text": "All same."}]
    summary = bad.summarize_diff(segments)
    assert summary["removed_words"] == 0
    assert summary["added_words"] == 0


# --------------------------- build_card_diff -----------------------------


def test_build_card_diff_pairs_pages_by_number() -> None:
    """For each page that exists in BOTH pre + post OCR, produce a
    page diff. Pages present in only one side become wholesale
    add/remove."""
    pre_pages = [
        {"page": 1, "text": "Page one before. Sentence two."},
        {"page": 2, "text": "Page two before."},
    ]
    post_pages = [
        {"page": 1, "text": "Page one after. Sentence two."},
        {"page": 2, "text": "Page two before."},
    ]
    diff = bad.build_card_diff(pre_pages, post_pages)
    assert len(diff["pages"]) == 2
    # Page 1 has a real change; page 2 is unchanged.
    page1 = diff["pages"][0]
    assert page1["page_no"] == 1
    assert any(s["kind"] in ("removed", "added") for s in page1["segments"])
    page2 = diff["pages"][1]
    assert all(s["kind"] == "equal" for s in page2["segments"])


def test_build_card_diff_marks_partial_ocr_when_post_runs_short() -> None:
    """When post-edit OCR has fewer pages than pre-edit, the diff
    bounds to the overlap and surfaces ``ocr_status: "partial"``
    + ``ocr_max_page`` + ``total_pre_pages`` so the renderer can
    show an "OCR INCOMPLETE past page N" banner.

    Without this, content-filter rejection mid-card (2 cases in
    Sprint 4h's real run) would render every pre-only page as
    "all removed", framing OCR truncation as deliberate redaction.
    """
    pre_pages = [
        {"page": 1, "text": "Keep."},
        {"page": 2, "text": "Pre-only content."},
    ]
    post_pages = [
        {"page": 1, "text": "Keep."},
    ]
    diff = bad.build_card_diff(pre_pages, post_pages)
    # Diff bounded to page 1 (the overlap); partial flag set so the
    # renderer can warn instead of misframing.
    assert len(diff["pages"]) == 1
    assert diff["pages"][0]["page_no"] == 1
    assert diff["summary"]["ocr_status"] == "partial"
    assert diff["summary"]["ocr_max_page"] == 1
    assert diff["summary"]["total_pre_pages"] == 2


def test_build_card_diff_whole_page_redacted_via_empty_text() -> None:
    """A whole-page redaction with successful OCR yields ``post_text
    == ""`` for that page — the diff legitimately renders the page
    as all-removed. Distinct from OCR truncation, where the page
    key is absent entirely (caught by the partial test above).
    """
    pre_pages = [
        {"page": 1, "text": "Keep."},
        {"page": 2, "text": "Whole page redacted away."},
    ]
    post_pages = [
        {"page": 1, "text": "Keep."},
        {"page": 2, "text": ""},  # OCR ran but found no text
    ]
    diff = bad.build_card_diff(pre_pages, post_pages)
    assert len(diff["pages"]) == 2
    assert diff["summary"]["ocr_status"] == "complete"
    page2 = diff["pages"][1]
    assert any(s["kind"] == "removed" for s in page2["segments"])


def test_build_card_diff_summary_aggregates_across_pages() -> None:
    pre_pages = [
        {"page": 1, "text": "Page one with many words. Redacted sentence here."},
        {"page": 2, "text": "All equal text."},
    ]
    post_pages = [
        {"page": 1, "text": "Page one with many words."},
        {"page": 2, "text": "All equal text."},
    ]
    diff = bad.build_card_diff(pre_pages, post_pages)
    summary = diff["summary"]
    # 3 words removed from page 1 ("Redacted sentence here" without the period).
    assert summary["removed_words"] >= 3
    assert summary["added_words"] == 0
    # modified_pages records page 1 (the only page with any diff).
    assert summary["modified_pages"] == [1]
    assert summary["first_change_page"] == 1


def test_build_card_diff_empty_when_no_changes() -> None:
    pre_pages = [{"page": 1, "text": "Same."}]
    post_pages = [{"page": 1, "text": "Same."}]
    diff = bad.build_card_diff(pre_pages, post_pages)
    assert diff["summary"]["removed_words"] == 0
    assert diff["summary"]["added_words"] == 0
    assert diff["summary"]["modified_pages"] == []
    assert diff["summary"]["first_change_page"] is None
