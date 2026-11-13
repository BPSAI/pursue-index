"""scripts/intermediates.py: the release asset of OCR text, cleaning sidecars and vectors."""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import intermediates  # noqa: E402


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data-root"
    for card in ("aaaa000000000001", "bbbb000000000002"):
        d = root / "ocr" / card
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"card_id": card, "engine": "x"}))
        (d / "pages.jsonl").write_text('{"page": 1, "text": "t"}\n')
        (d / "pages_cleaned.jsonl").write_text('{"page": 1, "text": "t"}\n')
        (d / "pages.jsonl.pre-backup").write_text("old")  # never packed
    (root / "ocr" / "bbbb000000000002" / "pages_cleaned_qc.jsonl").write_text("{}\n")
    emb = root / "embeddings" / intermediates.EMBED_MODEL
    emb.mkdir(parents=True)
    (emb / "index.json").write_text("[]")
    (emb / "vectors.bin").write_bytes(b"\0" * 16)
    return root


def test_pack_takes_only_the_builder_inputs(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    arcs = [arc for arc, _src in intermediates.collect(root)]
    assert arcs == sorted(arcs)
    assert "ocr/aaaa000000000001/pages.jsonl" in arcs
    assert "ocr/bbbb000000000002/pages_cleaned_qc.jsonl" in arcs
    assert not any("pre-backup" in a for a in arcs)
    assert arcs[:2] == [f"embeddings/{intermediates.EMBED_MODEL}/index.json",
                         f"embeddings/{intermediates.EMBED_MODEL}/vectors.bin"]


def test_pack_is_deterministic_and_self_describing(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    one = intermediates.pack(root, tmp_path / "one", "v9.9.9")
    two = intermediates.pack(root, tmp_path / "two", "v9.9.9")
    assert one.read_bytes() == two.read_bytes()
    digest = intermediates.sha256_bytes(one.read_bytes())
    assert (tmp_path / "one" / "SHA256SUMS").read_text() == f"{digest}  {one.name}\n"
    manifest = intermediates.unpack(one, tmp_path / "x")
    assert manifest["schema"] == intermediates.SCHEMA and manifest["label"] == "v9.9.9"
    assert len(manifest["files"]) == 9  # 2 cards x 3 files, 1 QC sidecar, 2 embedding files


def test_a_tarball_that_does_not_match_its_sums_is_refused(tmp_path: Path) -> None:
    tar = intermediates.pack(_data_root(tmp_path), tmp_path / "o", "v1")
    (tmp_path / "o" / "SHA256SUMS").write_text(f"{'0' * 64}  {tar.name}\n")
    with pytest.raises(SystemExit, match="SHA256SUMS"):
        intermediates._check_sums(tar)


def _tar(tmp_path: Path, members: dict[str, bytes], manifest: dict | None = None) -> Path:
    path = tmp_path / "t.tar.gz"
    with tarfile.open(path, mode="w:gz") as tar:
        if manifest is not None:
            body = json.dumps(manifest).encode()
            tar.addfile(intermediates._tarinfo(intermediates.MANIFEST_NAME, len(body)),
                        io.BytesIO(body))
        for name, data in members.items():
            tar.addfile(intermediates._tarinfo(name, len(data)), io.BytesIO(data))
    return path


@pytest.mark.parametrize("name", ["../escape", "/abs/path", "ocr/../../x"])
def test_unpack_refuses_members_outside_the_destination(tmp_path: Path, name: str) -> None:
    with pytest.raises(SystemExit, match="refusing tar member"):
        intermediates.unpack(_tar(tmp_path, {name: b"x"}), tmp_path / "dest")
    assert not (tmp_path / "escape").exists()


def test_unpack_refuses_a_file_that_does_not_match_the_manifest(tmp_path: Path) -> None:
    manifest = {"schema": intermediates.SCHEMA, "label": "v1",
                "files": {"ocr/a/pages.jsonl": {"sha256": "0" * 64, "bytes": 1}}}
    tar = _tar(tmp_path, {"ocr/a/pages.jsonl": b"x"}, manifest)
    with pytest.raises(SystemExit, match="does not match MANIFEST"):
        intermediates.unpack(tar, tmp_path / "dest")


def _payloads(d: Path, cleaned_meta: dict, rows: list[dict]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "pages.json").write_text("[]")
    (d / "pages-cleaned.json").write_text(json.dumps({"meta": cleaned_meta, "pages": rows}))
    (d / "embed_index.json").write_text("[]")
    (d / "embeddings.bin").write_bytes(b"\0")


def test_compare_ignores_only_the_build_timestamp(tmp_path: Path) -> None:
    rows = [{"card_id": "a", "page": 1, "text": "t"}]
    _payloads(tmp_path / "pub", {"generated_at": "then", "page_count": 1}, rows)
    _payloads(tmp_path / "out", {"generated_at": "now", "page_count": 1}, rows)
    assert intermediates.compare(tmp_path / "out", tmp_path / "pub") == []

    _payloads(tmp_path / "out", {"generated_at": "now", "page_count": 1},
              [{"card_id": "a", "page": 1, "text": "t", "ocr_page_sha256": "x"}])
    problems = intermediates.compare(tmp_path / "out", tmp_path / "pub")
    assert problems == [
        "pages-cleaned.json: 1 rows; differing fields {'ocr_page_sha256': 1}"]


def test_sums_are_required_and_a_pinned_sha256_must_match(tmp_path: Path) -> None:
    tar = intermediates.pack(_data_root(tmp_path), tmp_path / "o", "v1")
    digest = intermediates._check_sums(tar, intermediates._sha256_file(tar))
    with pytest.raises(SystemExit, match="is not the expected"):
        intermediates._check_sums(tar, "0" * 64)
    (tmp_path / "o" / "SHA256SUMS").unlink()
    with pytest.raises(SystemExit, match="no SHA256SUMS"):
        intermediates._check_sums(tar, digest)


def test_unpack_refuses_a_tarball_over_the_limits_before_writing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tar = _tar(tmp_path, {"ocr/a/pages.jsonl": b"x" * 64})
    monkeypatch.setattr(intermediates, "MAX_MEMBER_BYTES", 16)
    with pytest.raises(SystemExit, match="unpack limits"):
        intermediates.unpack(tar, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
    monkeypatch.setattr(intermediates, "MAX_MEMBER_BYTES", 1 << 20)
    monkeypatch.setattr(intermediates, "MAX_TOTAL_BYTES", 16)
    with pytest.raises(SystemExit, match="unpack limits"):
        intermediates.unpack(tar, tmp_path / "dest")


def test_a_symlinked_card_directory_is_never_packed(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "pages.jsonl").write_text("secret\n")
    (root / "ocr" / "cccc000000000003").symlink_to(outside, target_is_directory=True)
    assert not any("cccc" in arc for arc, _src in intermediates.collect(root))


def test_rebuild_check_needs_a_pin_or_an_explicit_waiver(tmp_path: Path) -> None:
    tar = intermediates.pack(_data_root(tmp_path), tmp_path / "o", "v1")
    with pytest.raises(SystemExit, match="--expect-sha256"):
        intermediates.rebuild_check(tar)


def test_unpack_refuses_a_missing_manifest_or_duplicate_members(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"no readable MANIFEST\.json"):
        intermediates.unpack(_tar(tmp_path, {"ocr/a/pages.jsonl": b"x"}), tmp_path / "d1")
    path = tmp_path / "dup.tar.gz"
    with tarfile.open(path, mode="w:gz") as tar:
        for _ in range(2):
            tar.addfile(intermediates._tarinfo("ocr/a/pages.jsonl", 1), io.BytesIO(b"x"))
    with pytest.raises(SystemExit, match="duplicate tar member"):
        intermediates.unpack(path, tmp_path / "d2")


def test_binary_mode_sha256sums_are_accepted(tmp_path: Path) -> None:
    tar = intermediates.pack(_data_root(tmp_path), tmp_path / "o", "v1")
    digest = intermediates._sha256_file(tar)
    (tmp_path / "o" / "SHA256SUMS").write_text(f"{digest} *{tar.name}\n")
    assert intermediates._check_sums(tar, digest) == digest
