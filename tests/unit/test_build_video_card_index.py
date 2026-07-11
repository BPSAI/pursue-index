"""Tests for `scripts/build_video_card_index.py`.

The build step walks the asset-bytes registry and emits an allow-list of
`card_id`s that have a playable ``<card_id>.mp4`` current-pointer object
in R2 (bucket ``pursue-pdfs``, served same-origin by the Worker at
``/video/<card_id>.mp4``). The card-detail page unions this list to decide
whether a VID/AUD card can play from our own R2 pipeline (the primary
player) or must fall back to the DVIDS embed (cards whose bytes were never
ingested — e.g. all of Release 1 as of 2026-07).

Only ``.mp4`` current-pointer rows count. Archive-only rows
(``archive/<sha>.mp4`` with no ``<card_id>.mp4`` current pointer) do NOT,
because the ``/video/`` route serves the current pointer key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_video_card_index  # type: ignore[import-not-found] # noqa: E402


def _reg_line(card_id: str, current_key: str, archive_key: str = "") -> str:
    return json.dumps(
        {
            "card_id": card_id,
            "current_key": current_key,
            "archive_key": archive_key or f"archive/{card_id}.mp4",
        }
    )


def test_predicate_true_for_mp4_current_pointer() -> None:
    assert build_video_card_index.is_playable_video_row(
        {"card_id": "abc", "current_key": "abc.mp4"}
    )


def test_predicate_false_for_pdf_current_pointer() -> None:
    assert not build_video_card_index.is_playable_video_row(
        {"card_id": "abc", "current_key": "abc.pdf"}
    )


def test_predicate_false_when_no_current_key() -> None:
    # Archive-only row (no <card_id>.mp4 pointer) is not servable at /video/.
    assert not build_video_card_index.is_playable_video_row(
        {"card_id": "abc", "current_key": "", "archive_key": "archive/x.mp4"}
    )


def test_predicate_false_for_missing_card_id() -> None:
    assert not build_video_card_index.is_playable_video_row(
        {"card_id": "", "current_key": "abc.mp4"}
    )


def test_build_collects_mp4_card_ids(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    out_path = tmp_path / "video-card-ids.json"
    registry.write_text(
        "\n".join(
            [
                _reg_line("vid1", "vid1.mp4"),
                _reg_line("aud1", "aud1.mp4"),
                _reg_line("pdf1", "pdf1.pdf"),  # not a video
            ]
        )
        + "\n"
    )

    build_video_card_index.build(registry_path=registry, out_path=out_path)

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == ["aud1", "vid1"]  # sorted
    assert out["count"] == 2
    assert "generated_at" in out


def test_build_dedupes_repeated_card_ids(tmp_path: Path) -> None:
    # A card can accrue multiple registry rows (byte re-publish). The
    # current-pointer stays one object; the allow-list must dedupe.
    registry = tmp_path / "registry.jsonl"
    out_path = tmp_path / "out.json"
    registry.write_text(
        "\n".join([_reg_line("dup", "dup.mp4"), _reg_line("dup", "dup.mp4")]) + "\n"
    )

    build_video_card_index.build(registry_path=registry, out_path=out_path)

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == ["dup"]
    assert out["count"] == 1


def test_build_tolerates_blank_and_malformed_lines(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    out_path = tmp_path / "out.json"
    registry.write_text(
        "\n".join(
            [
                "",
                "not json at all",
                _reg_line("good", "good.mp4"),
                "   ",
            ]
        )
        + "\n"
    )

    build_video_card_index.build(registry_path=registry, out_path=out_path)

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == ["good"]


def test_build_empty_registry_yields_empty_list(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    out_path = tmp_path / "out.json"
    registry.write_text("")

    build_video_card_index.build(registry_path=registry, out_path=out_path)

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == []
    assert out["count"] == 0


def test_build_missing_registry_yields_empty_list(tmp_path: Path) -> None:
    registry = tmp_path / "does-not-exist.jsonl"
    out_path = tmp_path / "out.json"

    build_video_card_index.build(registry_path=registry, out_path=out_path)

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == []
