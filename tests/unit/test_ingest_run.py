"""Tests for the ingest-run orchestrator (plan step 7).

The orchestrator is a thin shell: gate-check, snapshot promotion to
latest.json, and a summary of what downstream stages need to run.
Heavy lifting (download/ocr/embed) stays under the existing pursue
download/ocr/embed CLI surfaces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.ingest_run import (  # noqa: E402
    locate_snapshot,
    promote_snapshot,
    summarize_ingest_work,
)


def test_locate_snapshot_finds_full_sha_match(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    full_sha = "abc123" + "0" * 58
    target = snapshots / f"{full_sha}.json"
    target.write_text("{}")
    assert locate_snapshot(full_sha, snapshots) == target


def test_locate_snapshot_finds_prefix_match(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    target = snapshots / ("65572b38d27c" + "0" * 52 + ".json")
    target.write_text("{}")
    assert locate_snapshot("65572b38d27c", snapshots) == target


def test_locate_snapshot_returns_none_when_missing(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    assert locate_snapshot("doesnotexist", snapshots) is None


def test_promote_snapshot_copies_to_manifest_path(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "abc", "cards": []}')
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)
    assert manifest.read_text() == snapshot.read_text()


def test_promote_snapshot_overwrites_existing_manifest(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "new"}')
    manifest = tmp_path / "latest.json"
    manifest.write_text('{"csv_sha256": "old"}')
    promote_snapshot(snapshot, manifest)
    assert "new" in manifest.read_text()
    assert "old" not in manifest.read_text()


def test_promote_snapshot_mirrors_to_build_manifest(tmp_path: Path) -> None:
    """The build-side mirror at web/src/data/manifest.json must also be
    updated, or Astro builds against a stale manifest and renamed-card
    pages don't ship — caught in production on 2026-05-12 evening."""
    # Recreate the conventional layout: <repo>/data/manifests/latest.json
    # and <repo>/web/src/data/manifest.json
    repo_root = tmp_path / "repo"
    pipeline = repo_root / "data" / "manifests"
    pipeline.mkdir(parents=True)
    build_dir = repo_root / "web" / "src" / "data"
    build_dir.mkdir(parents=True)

    snapshot = pipeline / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "new", "cards": []}')
    manifest = pipeline / "latest.json"
    promote_snapshot(snapshot, manifest)

    build_manifest = build_dir / "manifest.json"
    assert build_manifest.exists(), "build-side mirror must be created"
    assert build_manifest.read_text() == snapshot.read_text()


def test_promote_snapshot_skips_build_mirror_when_layout_absent(tmp_path: Path) -> None:
    """Promotion must still succeed when web/src/data/ doesn't exist
    (e.g., CLI-only checkouts without npm install)."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}")
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)  # must not raise
    assert manifest.read_text() == snapshot.read_text()


# --- summarize_ingest_work ---


def test_summarize_no_new_content_minimal_work() -> None:
    """Tranches with no Class B and no Class C-approved-as-new are
    'metadata-only': just promote and rebuild deploy mirrors. No
    download/OCR/embed needed."""
    diff = {
        "renames_confirmed": [],
        "new_content": [],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [{"card_id": "abc", "diffs": []}] * 5,
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_download"] == []
    assert summary["needs_ocr"] == []
    assert summary["needs_embed"] == []
    assert summary["metadata_only"] is True


def test_summarize_class_b_new_content_needs_download_ocr_embed() -> None:
    """Class B (net-new content) needs the full pipeline."""
    diff = {
        "renames_confirmed": [],
        "new_content": [
            {"new_card_id": "newcard1", "title": "X", "asset_url": "https://x/a.pdf"},
            {"new_card_id": "newcard2", "title": "Y", "asset_url": None},
        ],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    # newcard1 has asset → all three stages; newcard2 (no asset) only manifest.
    assert "newcard1" in summary["needs_download"]
    assert "newcard1" in summary["needs_ocr"]
    assert "newcard1" in summary["needs_embed"]
    assert "newcard2" not in summary["needs_download"]
    assert summary["metadata_only"] is False


def test_summarize_restored_modified_flags_for_inspection() -> None:
    """A restored_modified entry doesn't need OCR/embed automatically;
    it needs operator inspection of what changed."""
    diff = {
        "renames_confirmed": [], "new_content": [], "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [
            {"new_card_id": "modcard", "new_asset_url": "https://x/m.pdf"},
        ],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_inspection"] == ["modcard"]
    assert "modcard" not in summary["needs_ocr"]
    assert "modcard" not in summary["needs_embed"]


def test_summarize_renames_dont_need_download() -> None:
    """Class A renames are byte-identical to existing archive entries.
    No new download/OCR/embed work."""
    diff = {
        "renames_confirmed": [
            {"old_card_id": "old1", "new_card_id": "new1",
             "byte_sha256": "ff" * 32},
        ],
        "new_content": [], "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_download"] == []
    assert summary["needs_ocr"] == []
    assert summary["needs_embed"] == []
    assert summary["metadata_only"] is True
