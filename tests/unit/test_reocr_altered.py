"""Tests for ``scripts/reocr_altered.py`` (Sprint 4h Phase 1).

The script OCRs the 70 post-edit byte versions for cards whose
upstream bytes were silently re-published on 2026-05-14 (the May-14
silent-overlay class). 9 of the 79 multi-sha cards are .mp4 (DVIDS
video preservation) — OCR doesn't apply, those are skipped.

These tests pin the pure helpers + the orchestrator's contract.
The actual Anthropic API calls + R2 fetches are mocked everywhere
— no CI spend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reocr_altered as ra  # noqa: E402


# --------------------------- select_ocr_targets --------------------------

def _entry(byte_sha: str, ext: str, size: int = 100, ts: str = "2026-05-14T00:00:00Z") -> dict:
    return {
        "byte_sha256": byte_sha,
        "byte_size": size,
        "fetched_at": ts,
        "archive_key": f"archive/{byte_sha}.{ext}",
        "asset_filename": f"doc.{ext}",
        "is_current": False,
    }


def test_select_ocr_targets_filters_to_pdf_only() -> None:
    """9 of 79 multi-sha cards are .mp4 (DVIDS audio preservation);
    OCR doesn't apply, so they're excluded. PDFs only."""
    history = {
        "pdf_card": [
            {**_entry("a" * 64, "pdf"), "is_current": True},
            _entry("b" * 64, "pdf"),
        ],
        "video_card": [
            {**_entry("c" * 64, "mp4"), "is_current": True},
            _entry("d" * 64, "mp4"),
        ],
    }
    targets = ra.select_ocr_targets(history)
    assert [t["card_id"] for t in targets] == ["pdf_card"]


def test_select_ocr_targets_picks_current_entry_for_each_card() -> None:
    """We OCR the CURRENT (post-edit) bytes — that's the version the
    iframe serves. The diff page will pair it against the pre-edit
    OCR from pages-cleaned.json."""
    history = {
        "x": [
            {**_entry("aaa" + "a" * 61, "pdf"), "is_current": True},
            _entry("bbb" + "b" * 61, "pdf"),
        ],
    }
    [target] = ra.select_ocr_targets(history)
    assert target["card_id"] == "x"
    assert target["byte_sha256"] == "aaa" + "a" * 61
    assert target["archive_key"] == "archive/" + ("aaa" + "a" * 61) + ".pdf"


def test_select_ocr_targets_sorts_deterministically() -> None:
    """Order matters for resume semantics — operator may interrupt
    a run and resume; the next run must start from the same place.
    """
    history = {
        "z_card": [{**_entry("a" * 64, "pdf"), "is_current": True}],
        "a_card": [{**_entry("b" * 64, "pdf"), "is_current": True}],
        "m_card": [{**_entry("c" * 64, "pdf"), "is_current": True}],
    }
    targets = ra.select_ocr_targets(history)
    assert [t["card_id"] for t in targets] == ["a_card", "m_card", "z_card"]


def test_select_ocr_targets_skips_empty_history() -> None:
    assert ra.select_ocr_targets({}) == []


# --------------------------- resume_from_page ----------------------------


def test_resume_from_page_returns_1_when_file_missing(tmp_path: Path) -> None:
    assert ra.resume_from_page(tmp_path / "nope.jsonl") == 1


def test_resume_from_page_returns_next_when_partial(tmp_path: Path) -> None:
    """Operator interrupted after page 3 → next run resumes at page 4."""
    path = tmp_path / "pages.jsonl"
    path.write_text("\n".join(
        json.dumps({"page": i, "text": "x", "confidence": 0.9})
        for i in (1, 2, 3)
    ) + "\n")
    assert ra.resume_from_page(path) == 4


def test_resume_from_page_handles_blank_lines_and_trailing_newlines(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    path.write_text(json.dumps({"page": 1, "text": "x", "confidence": 0.9}) + "\n\n\n")
    assert ra.resume_from_page(path) == 2


def test_resume_from_page_returns_1_on_corrupt_file(tmp_path: Path) -> None:
    """A torn write (process killed mid-line) shouldn't lose ALL
    progress, but it MUST NOT silently double-OCR pages. We treat a
    corrupt file as "start over" — the operator can manually inspect
    if pages were already produced."""
    path = tmp_path / "pages.jsonl"
    path.write_text(
        json.dumps({"page": 1, "text": "x", "confidence": 0.9}) + "\n{torn"
    )
    # Corrupt JSON on line 2 → bail; tolerated entries before are
    # rejected (safer to start over than misalign page indices).
    assert ra.resume_from_page(path) == 1


# --------------------------- cost tracking -------------------------------


def test_track_usage_accumulates_token_counts() -> None:
    tracker = ra.UsageTracker()
    tracker.add(input_tokens=100, output_tokens=50)
    tracker.add(input_tokens=200, output_tokens=80)
    assert tracker.input_tokens == 300
    assert tracker.output_tokens == 130


def test_estimate_cost_uses_sonnet_46_pricing() -> None:
    """Sonnet 4.6 pricing (per Anthropic doc): $3/MTok input,
    $15/MTok output. 1MTok = 10**6 tokens."""
    cost = ra.estimate_cost_usd(input_tokens=1_000_000, output_tokens=1_000_000)
    assert abs(cost - (3.0 + 15.0)) < 1e-9


def test_estimate_cost_zero_when_no_usage() -> None:
    assert ra.estimate_cost_usd(input_tokens=0, output_tokens=0) == 0.0


# --------------------------- ocr_card orchestrator -----------------------


def test_ocr_card_skips_when_already_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Resume contract: if pages.jsonl has all N pages, the card is
    complete and we don't re-OCR. This is what makes the script
    safely re-runnable."""
    out_dir = tmp_path / "altered-ocr"
    card_dir = out_dir / "x"
    card_dir.mkdir(parents=True)
    # 3 pages already OCR'd.
    (card_dir / "pages.jsonl").write_text("\n".join(
        json.dumps({"page": i, "text": "x", "confidence": 0.9})
        for i in (1, 2, 3)
    ) + "\n")

    target = {
        "card_id": "x",
        "byte_sha256": "a" * 64,
        "archive_key": "archive/" + "a" * 64 + ".pdf",
        "asset_filename": "doc.pdf",
    }
    fake_r2 = MagicMock()
    fake_rasterize = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    fake_ocr = MagicMock()
    tracker = ra.UsageTracker()
    ra.ocr_card(
        target=target,
        out_dir=out_dir,
        r2_client=fake_r2,
        rasterize=fake_rasterize,
        ocr_image=fake_ocr,
        tracker=tracker,
        cost_cap_usd=10.0,
    )
    # Bytes fetch + rasterization happened (so we know the page count),
    # but OCR was NOT called for any page.
    fake_r2.get_object.assert_called_once()
    fake_rasterize.assert_called_once()
    fake_ocr.assert_not_called()


def test_ocr_card_resumes_from_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If pages.jsonl has pages 1+2 but not 3, OCR only page 3."""
    out_dir = tmp_path / "altered-ocr"
    card_dir = out_dir / "x"
    card_dir.mkdir(parents=True)
    (card_dir / "pages.jsonl").write_text("\n".join(
        json.dumps({"page": i, "text": "x", "confidence": 0.9})
        for i in (1, 2)
    ) + "\n")

    target = {
        "card_id": "x",
        "byte_sha256": "a" * 64,
        "archive_key": "archive/" + "a" * 64 + ".pdf",
        "asset_filename": "doc.pdf",
    }
    fake_r2 = MagicMock()
    fake_rasterize = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])  # 3 pages
    fake_ocr = MagicMock(return_value=("page 3 text", 0.95))
    tracker = ra.UsageTracker()
    ra.ocr_card(
        target=target,
        out_dir=out_dir,
        r2_client=fake_r2,
        rasterize=fake_rasterize,
        ocr_image=fake_ocr,
        tracker=tracker,
        cost_cap_usd=10.0,
    )
    # ocr_image called exactly once (for page 3 only).
    assert fake_ocr.call_count == 1
    # pages.jsonl now has all 3 pages.
    contents = (card_dir / "pages.jsonl").read_text().strip().split("\n")
    assert len(contents) == 3
    assert json.loads(contents[2])["page"] == 3


def test_ocr_card_respects_cost_cap_mid_run(
    tmp_path: Path
) -> None:
    """If the running cost would exceed cost_cap_usd, stop and raise
    CostCapExceeded so the operator can decide whether to re-up or
    abandon. Cards that completed before the cap stay completed."""
    out_dir = tmp_path / "altered-ocr"
    target = {
        "card_id": "x",
        "byte_sha256": "a" * 64,
        "archive_key": "archive/" + "a" * 64 + ".pdf",
        "asset_filename": "doc.pdf",
    }
    fake_r2 = MagicMock()
    fake_rasterize = MagicMock(return_value=[MagicMock(), MagicMock(), MagicMock()])
    # Pretend each call costs $5 (huge input tokens).
    def fake_ocr_with_huge_cost(img):
        # Simulate a really expensive call by writing directly to the
        # tracker after each call returns.
        return ("text", 0.9)
    fake_ocr = MagicMock(side_effect=fake_ocr_with_huge_cost)

    tracker = ra.UsageTracker()
    # Force the tracker to over-cap after the first call by recording
    # tokens via the test seam.
    def _tracking_ocr(img):
        result = fake_ocr_with_huge_cost(img)
        tracker.add(input_tokens=2_000_000, output_tokens=1_000_000)  # $21 per call
        return result

    with pytest.raises(ra.CostCapExceeded):
        ra.ocr_card(
            target=target,
            out_dir=out_dir,
            r2_client=fake_r2,
            rasterize=fake_rasterize,
            ocr_image=_tracking_ocr,
            tracker=tracker,
            cost_cap_usd=10.0,
        )
    # Page 1 completed before the cap fired; pages.jsonl persists it.
    contents = (out_dir / "x" / "pages.jsonl").read_text().strip().split("\n")
    assert len(contents) == 1
    assert json.loads(contents[0])["page"] == 1
