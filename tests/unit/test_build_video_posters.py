"""Tests for the R2-sourced video-poster builder.

Poster generation now sources frames from our archived R2 bytes via the
NAS content-addressed mirror (``r2-mirror/archive/<sha>.mp4``), joined to
cards by the asset-bytes registry — NOT a DVIDS scrape or an operator
Desktop path. These tests exercise that path with ``extract_poster``
stubbed so no real ffmpeg/mp4 is needed.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_video_posters", REPO_ROOT / "scripts" / "build_video_posters.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_manifest(path: Path, cards: list[tuple[str, str]]) -> None:
    """Write a minimal manifest of ``(card_id, asset_type)`` pairs."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from pursue_index.scrape.manifest import save_manifest
    from pursue_index.scrape.types import CardMetadata, Manifest

    manifest = Manifest(
        source_url="https://example.gov/csv",
        fetched_at=datetime(2026, 8, 8, tzinfo=UTC),
        csv_sha256="a" * 64,
        cards=[
            CardMetadata(
                card_id=cid, title=f"card {cid}", asset_type=at, agency="DOD"
            )
            for cid, at in cards
        ],
    )
    save_manifest(manifest, path)


def _write_registry(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _mirror_mp4(mirror_root: Path, sha: str, data: bytes = b"\x00\x01") -> Path:
    target = mirror_root / "archive" / f"{sha}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_load_registry_sha_map_selects_mp4_rows_last_wins(tmp_path: Path):
    mod = _load_module()
    reg = tmp_path / "registry.jsonl"
    _write_registry(
        reg,
        [
            {"card_id": "aa", "byte_sha256": "sha_old", "current_key": "aa.mp4"},
            {"card_id": "aa", "byte_sha256": "sha_new", "current_key": "aa.mp4"},
            {"card_id": "bb", "byte_sha256": "sha_pdf", "current_key": "bb.pdf"},
            {"card_id": "cc", "byte_sha256": "sha_cc", "current_key": "cc.mp4"},
        ],
    )
    m = mod.load_registry_sha_map(reg)
    assert m == {"aa": "sha_new", "cc": "sha_cc"}


def test_resolve_mirror_mp4_present_and_absent(tmp_path: Path):
    mod = _load_module()
    _mirror_mp4(tmp_path, "deadbeef")
    assert mod._resolve_mirror_mp4(tmp_path, "deadbeef") is not None
    assert mod._resolve_mirror_mp4(tmp_path, "missing") is None


def test_prune_orphans_removes_absent_card_files_and_mapping(tmp_path: Path):
    mod = _load_module()
    posters = tmp_path / "posters"
    posters.mkdir()
    (posters / "keep.jpg").write_bytes(b"j")
    (posters / "orphan.jpg").write_bytes(b"j")
    mapping = {"keep": "keep.jpg", "orphan": "orphan.jpg"}
    removed = mod._prune_orphans(posters, {"keep"}, mapping)
    assert removed == ["orphan"]
    assert mapping == {"keep": "keep.jpg"}
    assert (posters / "keep.jpg").exists()
    assert not (posters / "orphan.jpg").exists()


def _stub_extract(mod):
    def _fake(video: Path, out_jpg: Path, at_fraction: float = 0.1) -> bool:
        out_jpg.parent.mkdir(parents=True, exist_ok=True)
        out_jpg.write_bytes(b"\xff\xd8\xff")  # non-zero stub jpg
        return True

    mod.extract_poster = _fake


def test_build_generates_posters_for_av_cards_from_mirror(tmp_path: Path):
    mod = _load_module()
    _stub_extract(mod)
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest, [("vid1", "VID"), ("aud1", "AUD"), ("pdf1", "PDF")]
    )
    reg = tmp_path / "registry.jsonl"
    _write_registry(
        reg,
        [
            {"card_id": "vid1", "byte_sha256": "sha_v1", "current_key": "vid1.mp4"},
            {"card_id": "aud1", "byte_sha256": "sha_a1", "current_key": "aud1.mp4"},
        ],
    )
    mirror = tmp_path / "r2-mirror"
    _mirror_mp4(mirror, "sha_v1")
    _mirror_mp4(mirror, "sha_a1")
    posters = tmp_path / "posters"

    rc = mod.build(
        manifest_path=manifest,
        registry_path=reg,
        mirror_root=mirror,
        posters_dir=posters,
    )
    assert rc == 0
    # Only the two A/V cards get posters; the PDF card is ignored.
    assert (posters / "vid1.jpg").exists()
    assert (posters / "aud1.jpg").exists()
    assert not (posters / "pdf1.jpg").exists()
    index = json.loads((posters / "index.json").read_text())
    assert set(index["posters"]) == {"vid1", "aud1"}
    assert index["count"] == 2


def test_build_prunes_orphan_and_keeps_existing(tmp_path: Path):
    mod = _load_module()
    _stub_extract(mod)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [("vid1", "VID")])
    reg = tmp_path / "registry.jsonl"
    _write_registry(
        reg, [{"card_id": "vid1", "byte_sha256": "s1", "current_key": "vid1.mp4"}]
    )
    mirror = tmp_path / "r2-mirror"
    _mirror_mp4(mirror, "s1")
    posters = tmp_path / "posters"
    posters.mkdir()
    # A pre-existing orphan poster keyed to a card no longer in the manifest.
    (posters / "gone.jpg").write_bytes(b"\xff\xd8\xff")
    (posters / "index.json").write_text(
        json.dumps({"posters": {"gone": "gone.jpg"}, "count": 1})
    )

    rc = mod.build(
        manifest_path=manifest,
        registry_path=reg,
        mirror_root=mirror,
        posters_dir=posters,
    )
    assert rc == 0
    assert not (posters / "gone.jpg").exists()
    index = json.loads((posters / "index.json").read_text())
    assert set(index["posters"]) == {"vid1"}


def test_build_skips_card_without_bytes_but_still_succeeds(tmp_path: Path):
    mod = _load_module()
    _stub_extract(mod)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [("vid1", "VID"), ("vid2", "VID")])
    reg = tmp_path / "registry.jsonl"
    _write_registry(
        reg,
        [
            {"card_id": "vid1", "byte_sha256": "s1", "current_key": "vid1.mp4"},
            {"card_id": "vid2", "byte_sha256": "s2", "current_key": "vid2.mp4"},
        ],
    )
    mirror = tmp_path / "r2-mirror"
    _mirror_mp4(mirror, "s1")  # vid2's byte deliberately absent
    posters = tmp_path / "posters"

    rc = mod.build(
        manifest_path=manifest,
        registry_path=reg,
        mirror_root=mirror,
        posters_dir=posters,
    )
    assert rc == 0
    assert (posters / "vid1.jpg").exists()
    assert not (posters / "vid2.jpg").exists()


def test_main_returns_1_when_mirror_root_missing(tmp_path: Path):
    mod = _load_module()
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [("vid1", "VID")])
    reg = tmp_path / "registry.jsonl"
    _write_registry(reg, [])
    rc = mod.main(
        [
            "--manifest",
            str(manifest),
            "--registry",
            str(reg),
            "--mirror-root",
            str(tmp_path / "does-not-exist"),
            "--posters-dir",
            str(tmp_path / "posters"),
        ]
    )
    assert rc == 1
