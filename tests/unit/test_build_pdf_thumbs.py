"""Tests for the PDF thumb-index pruning behavior.

``build_pdf_thumbs.py`` carries forward the prior ``thumbs/index.json`` on
every run, but never dropped entries for card ids that left the manifest
(a superseded card id stayed mapped to a thumb file forever). These tests
exercise the prune step with ``render_thumbnail`` untouched, since the
fresh/orphan paths never call it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_pdf_thumbs", REPO_ROOT / "scripts" / "build_pdf_thumbs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_manifest(path: Path, cards: list[tuple[str, str]]) -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from pursue_index.scrape.manifest import save_manifest
    from pursue_index.scrape.types import CardMetadata, Manifest

    manifest = Manifest(
        source_url="https://example.gov/csv",
        fetched_at=datetime(2026, 8, 8, tzinfo=UTC),
        csv_sha256="a" * 64,
        cards=[
            CardMetadata(
                card_id=cid,
                title=f"card {cid}",
                asset_type=at,
                agency="DOD",
                asset_filename=f"{cid}.pdf",
            )
            for cid, at in cards
        ],
    )
    save_manifest(manifest, path)


def test_prune_orphans_removes_entry_and_files(tmp_path: Path):
    mod = _load_module()
    thumbs_dir = tmp_path / "thumbs"
    thumbs_dir.mkdir()
    (thumbs_dir / "keep.webp").write_bytes(b"keep-webp")
    (thumbs_dir / "keep.sha256").write_text("keepsha")
    (thumbs_dir / "gone.webp").write_bytes(b"gone-webp")
    (thumbs_dir / "gone.sha256").write_text("gonesha")
    mapping = {"keep": "keep.webp", "gone": "gone.webp"}

    removed = mod._prune_orphans(thumbs_dir, {"keep"}, mapping)

    assert removed == ["gone"]
    assert mapping == {"keep": "keep.webp"}
    assert not (thumbs_dir / "gone.webp").exists()
    assert not (thumbs_dir / "gone.sha256").exists()
    assert (thumbs_dir / "keep.webp").exists()
    assert (thumbs_dir / "keep.sha256").exists()


def test_prune_orphans_leaves_valid_ids_untouched(tmp_path: Path):
    mod = _load_module()
    thumbs_dir = tmp_path / "thumbs"
    thumbs_dir.mkdir()
    (thumbs_dir / "keep.webp").write_bytes(b"keep-webp")
    (thumbs_dir / "keep.sha256").write_text("keepsha")
    mapping = {"keep": "keep.webp"}

    removed = mod._prune_orphans(thumbs_dir, {"keep"}, mapping)

    assert removed == []
    assert mapping == {"keep": "keep.webp"}
    assert (thumbs_dir / "keep.webp").exists()
    assert (thumbs_dir / "keep.sha256").exists()


def test_main_prunes_card_that_left_manifest(tmp_path: Path, capsys):
    mod = _load_module()
    mod._preflight = lambda args: True

    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [("keep", "PDF")])

    pdf_root = tmp_path / "pdfs"
    pdf_bytes = b"%PDF-1.4 fake"
    card_dir = pdf_root / "keep"
    card_dir.mkdir(parents=True)
    (card_dir / "keep.pdf").write_bytes(pdf_bytes)
    keep_sha = hashlib.sha256(pdf_bytes).hexdigest()

    thumbs_dir = tmp_path / "thumbs"
    thumbs_dir.mkdir()
    (thumbs_dir / "keep.webp").write_bytes(b"keep-webp")
    (thumbs_dir / "keep.sha256").write_text(keep_sha)
    (thumbs_dir / "gone.webp").write_bytes(b"gone-webp")
    (thumbs_dir / "gone.sha256").write_text("stale-sha")
    (thumbs_dir / "index.json").write_text(
        json.dumps({"thumbs": {"keep": "keep.webp", "gone": "gone.webp"}, "count": 2})
    )

    rc = mod.main(
        [
            "--manifest",
            str(manifest),
            "--pdf-root",
            str(pdf_root),
            "--thumbs-dir",
            str(thumbs_dir),
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "pruned=1" in out

    assert (thumbs_dir / "keep.webp").exists()
    assert (thumbs_dir / "keep.sha256").exists()
    assert not (thumbs_dir / "gone.webp").exists()
    assert not (thumbs_dir / "gone.sha256").exists()

    index = json.loads((thumbs_dir / "index.json").read_text())
    assert index["thumbs"] == {"keep": "keep.webp"}
    assert index["count"] == 1


def test_prune_orphans_ignores_ids_that_are_not_plain_filenames(tmp_path: Path):
    """A hostile index key must never reach an unlink outside thumbs_dir."""
    mod = _load_module()
    thumbs_dir = tmp_path / "thumbs"
    thumbs_dir.mkdir()
    victim = tmp_path / "victim.webp"
    victim.write_bytes(b"outside")
    mapping = {"../victim": "x.webp", "gone": "gone.webp"}
    (thumbs_dir / "gone.webp").write_bytes(b"gone")

    removed = mod._prune_orphans(thumbs_dir, set(), mapping)

    assert victim.exists()
    assert removed == ["gone"]
    assert "../victim" not in mapping
