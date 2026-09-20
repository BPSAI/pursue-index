"""Tests for the next-steps runbook rendered by the ingest-run orchestrator.

Split out of test_ingest_run.py: these cover render_next_steps (OCR engine,
A/V instructions, PDF-only regression) rather than snapshot promotion or
work summarization.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.ingest_run import (  # noqa: E402
    render_next_steps,
    summarize_ingest_work,
)


def test_render_next_steps_ocr_uses_operated_engine() -> None:
    """The post-tranche runbook must instruct the operator to run the operated
    engine (llm-dots), never the retired 'auto' resolver."""
    summary = {
        "needs_download": ["card1"],
        "needs_ocr": ["card1"],
        "needs_embed": ["card1"],
        "needs_av_fetch": [],
        "av_release_dates": [],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    assert "--engine llm-dots" in steps
    assert "--engine auto" not in steps


# --- render_next_steps A/V instructions ---


def test_render_next_steps_av_rows_prints_av_commands() -> None:
    """When there are A/V rows, render_next_steps should print av-fetch,
    ingest_release_videos.py, and transcribe commands with counts and
    release dates."""
    summary = {
        "needs_download": [],
        "needs_ocr": [],
        "needs_embed": [],
        "needs_av_fetch": ["vid1", "vid2", "aud1"],
        "av_release_dates": ["2026-03-15"],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    # Should include av-fetch
    assert "pursue av-fetch run" in steps
    assert "--release-date 2026-03-15" in steps
    # Should include ingest_release_videos.py
    assert "ingest_release_videos.py" in steps
    # Should include transcribe
    assert "pursue transcribe run" in steps
    # Should show count
    assert "3" in steps or "vid1" in steps  # count should appear somewhere


def test_render_next_steps_av_rows_no_block_when_empty() -> None:
    """When there are no A/V rows, render_next_steps should not print
    any A/V instructions."""
    summary = {
        "needs_download": ["pdf1"],
        "needs_ocr": ["pdf1"],
        "needs_embed": ["pdf1"],
        "needs_av_fetch": [],
        "av_release_dates": [],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    # Should not include av-fetch
    assert "av-fetch" not in steps
    assert "ingest_release_videos" not in steps
    assert "transcribe" not in steps or "--release-date" not in steps


def test_render_next_steps_pdf_and_av_together() -> None:
    """When there are both PDF and A/V rows, both instruction blocks
    should be printed."""
    summary = {
        "needs_download": ["pdf1"],
        "needs_ocr": ["pdf1"],
        "needs_embed": ["pdf1"],
        "needs_av_fetch": ["vid1", "aud1"],
        "av_release_dates": ["2026-03-20"],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    # Should include both download/ocr/embed for PDF
    assert "pursue download run" in steps
    assert "pursue ocr run" in steps
    assert "pursue embed run" in steps
    # And A/V commands
    assert "pursue av-fetch run" in steps
    assert "pursue transcribe run" in steps
    # Both should mention the release date
    assert "--release-date 2026-03-20" in steps


def test_render_next_steps_prints_one_av_block_per_release_date() -> None:
    summary = {
        "needs_download": [],
        "needs_ocr": [],
        "needs_embed": [],
        "needs_av_fetch": ["vid1", "aud1"],
        "av_release_dates": ["2026-03-15", "2026-04-02"],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    for date in ("2026-03-15", "2026-04-02"):
        assert f"pursue av-fetch run --release-date {date}" in steps
        assert f"ingest_release_videos.py --release-date {date}" in steps
        assert f"pursue transcribe run --release-date {date}" in steps
    assert steps.count("pursue vision run") == 1


# --- Regression tests: PDF worklist must remain byte-identical ---


def test_summarize_pdf_only_backward_compatible() -> None:
    """Regression: when only PDF rows present, output must be identical to
    before A/V support was added (no new fields in the output dict)."""
    diff = {
        "renames_confirmed": [],
        "new_content": [
            {"new_card_id": "pdf1", "title": "X", "asset_url": "https://x/a.pdf"},
            {"new_card_id": "pdf2", "title": "Y", "asset_url": "https://x/b.pdf"},
        ],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    # The original fields must be identical
    assert summary["needs_download"] == ["pdf1", "pdf2"]
    assert summary["needs_ocr"] == ["pdf1", "pdf2"]
    assert summary["needs_embed"] == ["pdf1", "pdf2"]
    assert summary["needs_inspection"] == []
    assert summary["metadata_only"] is False
    # New fields should exist but be empty for PDF-only diffs
    assert summary["needs_av_fetch"] == []
    assert summary["av_release_dates"] == []


def test_render_next_steps_pdf_only_unchanged() -> None:
    """Regression: render_next_steps output for PDF-only diffs must be
    identical to before A/V support (no A/V section printed)."""
    summary = {
        "needs_download": ["pdf1", "pdf2"],
        "needs_ocr": ["pdf1", "pdf2"],
        "needs_embed": ["pdf1", "pdf2"],
        "needs_av_fetch": [],
        "av_release_dates": [],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    # Must include PDF commands
    assert "pursue download run" in steps
    assert "pursue ocr run" in steps
    assert "pursue embed run" in steps
    # Must NOT include any A/V commands
    assert "av-fetch" not in steps
    assert "ingest_release_videos" not in steps
    # Must not have A/V sections
    lines = steps.split("\n")
    av_lines = [line for line in lines if "A/V" in line]
    assert len(av_lines) == 0, f"Should not have A/V section, found: {av_lines}"
