"""Tests for the per-card sidecar → web mirror build step.

Aggregates every ``pages_cleaned.jsonl`` under ``settings.ocr_dir`` into a
single ``web/public/data/pages-cleaned.json`` with metadata about the
pilot run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_pages_cleaned  # type: ignore[import-not-found] # noqa: E402


def _write_sidecar(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _write_manifest(path: Path, card_ids: list[str]) -> None:
    cards = [
        {
            "card_id": cid, "title": f"card {cid}", "agency": "FBI",
            "asset_type": "PDF",
            "asset_url": f"https://example.test/{cid}.pdf",
            "release_date": "2025-01-01", "redacted": False, "raw": {},
        }
        for cid in card_ids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_url": "https://example.test/x.csv",
        "fetched_at": "2026-05-09T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": cards,
    }))


def test_build_emits_pages_keyed_payload(tmp_path: Path) -> None:
    """Output is `{meta, pages}` with one row per sidecar entry."""
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [
            {"page": 1, "card_id": "c1", "text_cleaned": "p1",
             "model_id": "claude-haiku-4-5-20251001",
             "input_sha256": "a" * 64},
            {"page": 2, "card_id": "c1", "text_cleaned": "p2",
             "model_id": "claude-haiku-4-5-20251001",
             "input_sha256": "b" * 64},
        ],
    )
    _write_sidecar(
        ocr_dir / "c2" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c2", "text_cleaned": "p3",
          "model_id": "claude-haiku-4-5-20251001",
          "input_sha256": "c" * 64}],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "out" / "pages-cleaned.json"
    rc = build_pages_cleaned.build(
        ocr_dir=ocr_dir,
        manifest_path=manifest,
        out_path=out_path,
        source_tag="pilot-30-cards",
    )
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["meta"]["source"] == "pilot-30-cards"
    assert payload["meta"]["model_id"] == "claude-haiku-4-5-20251001"
    assert sorted(payload["meta"]["cards_covered"]) == ["c1", "c2"]
    pages = payload["pages"]
    assert len(pages) == 3
    page1 = next(p for p in pages if p["card_id"] == "c1" and p["page"] == 1)
    assert page1["text"] == "p1"
    assert page1["title"] == "card c1"  # joined from manifest


def test_build_handles_empty_ocr_dir(tmp_path: Path) -> None:
    """No sidecars yet → emits an empty pages array with metadata only."""
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    out_path = tmp_path / "out" / "pages-cleaned.json"
    rc = build_pages_cleaned.build(
        ocr_dir=ocr_dir,
        manifest_path=manifest,
        out_path=out_path,
        source_tag="empty",
    )
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["pages"] == []
    assert payload["meta"]["cards_covered"] == []


def test_build_raises_when_rows_have_mixed_model_id(tmp_path: Path) -> None:
    """nayru P3 #7 / vaivora P2 #2: ``meta.model_id`` is taken from the
    first row, so a build that mixes runs across models would silently
    misrepresent provenance. Force the operator to choose by asserting
    homogeneity — a mixed build is not a valid pilot artifact.
    """
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c1", "text_cleaned": "p1",
          "model_id": "claude-haiku-4-5-20251001",
          "input_sha256": "a" * 64, "prompt_sha256": "abc"}],
    )
    _write_sidecar(
        ocr_dir / "c2" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c2", "text_cleaned": "p2",
          "model_id": "claude-haiku-4-5-OTHER",  # Different model!
          "input_sha256": "b" * 64, "prompt_sha256": "abc"}],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "pages-cleaned.json"
    import pytest as _pytest
    with _pytest.raises(ValueError, match="model_id|prompt_sha256"):
        build_pages_cleaned.build(
            ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
            source_tag="t",
        )


def test_build_raises_when_rows_have_mixed_prompt_sha256(tmp_path: Path) -> None:
    """Same as the model_id case but for prompt drift."""
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c1", "text_cleaned": "p1",
          "model_id": "m", "input_sha256": "a" * 64,
          "prompt_sha256": "OLD"}],
    )
    _write_sidecar(
        ocr_dir / "c2" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c2", "text_cleaned": "p2",
          "model_id": "m", "input_sha256": "b" * 64,
          "prompt_sha256": "NEW"}],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "pages-cleaned.json"
    import pytest as _pytest
    with _pytest.raises(ValueError, match="prompt_sha256"):
        build_pages_cleaned.build(
            ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
            source_tag="t",
        )


def test_build_dedupes_repeated_rows_keeping_latest_generated_at(
    tmp_path: Path,
) -> None:
    """Codex P1: ``pages_cleaned.jsonl`` is append-only, so a re-run after
    a prompt bump produces two rows for the same (card_id, page). The
    build script must emit only the most-recent row per page.
    """
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [
            # Older row — superseded by the second.
            {
                "page": 1, "card_id": "c1", "text_cleaned": "old text",
                "model_id": "claude-haiku-4-5-20251001",
                "input_sha256": "a" * 64, "prompt_sha256": "old",
                "generated_at": "2026-05-01T00:00:00Z",
            },
            {
                "page": 1, "card_id": "c1", "text_cleaned": "new text",
                "model_id": "claude-haiku-4-5-20251001",
                "input_sha256": "a" * 64, "prompt_sha256": "new",
                "generated_at": "2026-05-09T00:00:00Z",
            },
            # A different page, only one row — must survive untouched.
            {
                "page": 2, "card_id": "c1", "text_cleaned": "p2",
                "model_id": "claude-haiku-4-5-20251001",
                "input_sha256": "b" * 64, "prompt_sha256": "new",
                "generated_at": "2026-05-09T00:00:00Z",
            },
        ],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    out_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
        source_tag="t",
    )
    payload = json.loads(out_path.read_text())
    pages = payload["pages"]
    assert len(pages) == 2
    page1 = next(p for p in pages if p["page"] == 1)
    assert page1["text"] == "new text"


def test_build_preserves_length_divergence_rows_with_empty_text(
    tmp_path: Path,
) -> None:
    """Codex P1 follow-up: ``length_divergence`` rows must STAY in the
    cleaned mirror so the UI's array-indexed pagination
    (``pages[activePage-1]`` in ``CardReaderView``) keeps page-N in the
    cleaned mirror pointing at the same source page as page-N in
    pages.json. Dropping a row shifts every later page's position and
    breaks deep links (#page-7) plus citations into the cleaned mirror.

    The fix: keep the row for structural alignment, clear
    ``text_cleaned`` to "" (no raw-OCR fallback leaks into a field
    labeled "cleaned"), and propagate the ``cleanup_skipped`` flag so
    the UI can render the appropriate "[Cleanup unavailable]" notice.
    """
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [
            {
                "page": 1, "card_id": "c1", "text_cleaned": "raw OCR text",
                "model_id": "m", "input_sha256": "a" * 64,
                "cleanup_skipped": "length_divergence",
            },
            {
                "page": 2, "card_id": "c1", "text_cleaned": "real cleanup",
                "model_id": "m", "input_sha256": "b" * 64,
            },
        ],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    out_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
        source_tag="t",
    )
    payload = json.loads(out_path.read_text())
    pages = payload["pages"]
    # Both rows survive so page-N indexing aligns with pages.json.
    assert len(pages) == 2
    page1 = next(p for p in pages if p["page"] == 1)
    # Raw OCR fallback does not leak into the "cleaned" text field.
    assert page1["text"] == ""
    # Cleanup-skipped flag is propagated so the UI can render a notice.
    assert page1["cleanup_skipped"] == "length_divergence"
    page2 = next(p for p in pages if p["page"] == 2)
    assert page2["text"] == "real cleanup"
    # Non-skipped rows do not carry a cleanup_skipped flag (or it's empty).
    assert not page2.get("cleanup_skipped")


def test_build_page_index_matches_raw_mirror_for_array_pagination(
    tmp_path: Path,
) -> None:
    """Codex P1 follow-up: the UI paginates by array index
    (``pages[activePage-1]`` in ``CardReaderView``) so any dropped row
    shifts later pages by 1 and mis-routes deep links like ``#page-7``.

    Contract: ALL ``cleanup_skipped`` rows are preserved (regardless of
    reason), so the cleaned mirror's page sequence matches the raw
    mirror's. ``length_divergence`` rows have ``text_cleaned`` cleared
    so raw OCR never ships under the cleaned label, but the row itself
    stays for alignment.
    """
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        _alignment_fixture_rows(),
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    out_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
        source_tag="t",
    )
    payload = json.loads(out_path.read_text())
    pages_for_c1 = sorted(
        (p for p in payload["pages"] if p["card_id"] == "c1"),
        key=lambda p: p["page"],
    )
    # Raw mirror's page sequence for c1 would be [1, 2, 3, 4]; cleaned
    # must match exactly so ``pages[activePage-1]`` resolves to the same
    # source page in either view.
    assert [p["page"] for p in pages_for_c1] == [1, 2, 3, 4]
    by_page = {p["page"]: p for p in pages_for_c1}
    # empty_input + length_divergence rows: empty cleaned text, flag set.
    assert by_page[2]["text"] == ""
    assert by_page[2]["cleanup_skipped"] == "empty_input"
    assert by_page[3]["text"] == ""
    assert by_page[3]["cleanup_skipped"] == "length_divergence"
    # Normal rows: cleaned text present, no skip flag.
    assert by_page[1]["text"] == "p1 cleaned"
    assert not by_page[1].get("cleanup_skipped")
    assert by_page[4]["text"] == "p4 cleaned"


def _alignment_fixture_rows() -> list[dict]:
    """Mixed normal + empty_input + length_divergence rows for one card.

    Keeps the alignment test small enough to clear the 50-line function
    cap while still exercising the full ``cleanup_skipped`` matrix.
    """
    return [
        {"page": 1, "card_id": "c1", "text_cleaned": "p1 cleaned",
         "model_id": "m", "input_sha256": "a" * 64},
        {"page": 2, "card_id": "c1", "text_cleaned": "",
         "model_id": "m", "input_sha256": "b" * 64,
         "cleanup_skipped": "empty_input"},
        {"page": 3, "card_id": "c1", "text_cleaned": "fallback raw",
         "model_id": "m", "input_sha256": "c" * 64,
         "cleanup_skipped": "length_divergence"},
        {"page": 4, "card_id": "c1", "text_cleaned": "p4 cleaned",
         "model_id": "m", "input_sha256": "d" * 64},
    ]


def test_build_skips_cards_without_sidecars(tmp_path: Path) -> None:
    """A card_id present in the manifest but with no sidecar is not in cards_covered."""
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c1", "text_cleaned": "x",
          "model_id": "m", "input_sha256": "0" * 64}],
    )
    # Empty stub for c2 (no JSONL) — must not crash, must not appear.
    (ocr_dir / "c2").mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
        source_tag="t",
    )
    payload = json.loads(out_path.read_text())
    assert payload["meta"]["cards_covered"] == ["c1"]
