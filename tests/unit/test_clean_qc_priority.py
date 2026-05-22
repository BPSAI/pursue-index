"""Tests for ``pursue_index.clean.qc.priority``.

Per-page review-priority scoring. Combines OCR confidence, length
divergence, gibberish density, and (when present) judge verdicts into
a 0-1 score. Higher = more likely to need review.
"""

from __future__ import annotations

import pytest

from pursue_index.clean.qc import priority


def test_score_page_clean_well_formed_returns_low_priority() -> None:
    """High confidence + reasonable text + no gibberish ⇒ low priority."""
    score = priority.score_page(
        raw_text="The quick brown fox jumps over the lazy dog. " * 5,
        cleaned_text="The quick brown fox jumps over the lazy dog. " * 5,
        ocr_confidence=0.98,
        qc_verdict="pass",
    )
    assert 0.0 <= score < 0.2


def test_score_page_low_confidence_raises_priority() -> None:
    score = priority.score_page(
        raw_text="some words here on a page.",
        cleaned_text="some words here on a page.",
        ocr_confidence=0.55,  # low
        qc_verdict=None,
    )
    assert score > 0.3


def test_score_page_length_divergence_raises_priority() -> None:
    """Cleaned text 3x the raw length ⇒ implausible, high priority."""
    score = priority.score_page(
        raw_text="short raw",
        cleaned_text="much much much longer cleaned text " * 10,
        ocr_confidence=0.95,
        qc_verdict=None,
    )
    assert score > 0.4


def test_score_page_judge_hard_fail_is_maximal() -> None:
    """Judge hard_fail ⇒ priority = 1.0 (ship-blocker)."""
    score = priority.score_page(
        raw_text="normal text on page",
        cleaned_text="normal text on page",
        ocr_confidence=0.95,
        qc_verdict="hard_fail",
    )
    assert score == 1.0


def test_score_page_judge_soft_fail_raises_priority() -> None:
    score_with_fail = priority.score_page(
        raw_text="text",
        cleaned_text="text",
        ocr_confidence=0.95,
        qc_verdict="soft_fail",
    )
    score_without = priority.score_page(
        raw_text="text",
        cleaned_text="text",
        ocr_confidence=0.95,
        qc_verdict="pass",
    )
    assert score_with_fail > score_without
    assert score_with_fail < 1.0


def test_score_page_gibberish_raises_priority() -> None:
    """High non-printable / random-char density ⇒ priority bump."""
    gibberish = "@#$%^*&xyz!@#$qwer$%^&zxcv@#$%" * 5
    score = priority.score_page(
        raw_text=gibberish,
        cleaned_text=gibberish,
        ocr_confidence=0.85,
        qc_verdict=None,
    )
    assert score > 0.3


def test_score_page_handles_empty_text() -> None:
    """Empty raw/cleaned shouldn't crash; should return moderate priority
    (something to review — could be a blank page or could be OCR failure)."""
    score = priority.score_page(
        raw_text="",
        cleaned_text="",
        ocr_confidence=0.0,
        qc_verdict=None,
    )
    assert 0.0 <= score <= 1.0
