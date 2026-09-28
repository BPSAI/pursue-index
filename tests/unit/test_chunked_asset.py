"""Chunked static assets: lossless split under the deploy size budget.

Cloudflare Workers refuses any single static asset over 25 MiB. A payload
under ``web/public/data`` that outgrows the budget is published as ordered
parts plus a ``<name>.chunks.json`` manifest, and every reader goes through
one loader that reassembles it byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pursue_index.release.chunked_asset import (
    BUDGET_BYTES,
    find_budget_violations,
    find_manifest_errors,
    manifest_path,
    read_asset_bytes,
    read_asset_json,
    write_asset,
)


def _manifest(path: Path) -> dict:
    return json.loads(manifest_path(path).read_text())


def test_budget_is_24_mib() -> None:
    assert BUDGET_BYTES == 24 * 1024 * 1024


def test_manifest_path_sits_next_to_the_asset(tmp_path: Path) -> None:
    assert manifest_path(tmp_path / "pages.json") == tmp_path / "pages.json.chunks.json"


def test_under_budget_asset_keeps_its_url_with_a_single_part_manifest(tmp_path: Path) -> None:
    path = tmp_path / "pages.json"
    data = b'[{"card_id":"a"}]'
    write_asset(path, data, budget=1024)
    assert path.read_bytes() == data
    m = _manifest(path)
    assert m["name"] == "pages.json"
    assert m["size"] == len(data)
    assert m["sha256"] == hashlib.sha256(data).hexdigest()
    assert m["parts"] == [{"path": "pages.json", "size": len(data)}]


def test_over_budget_asset_is_split_into_ordered_parts_under_budget(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.bin"
    data = bytes(range(256)) * 40  # 10,240 bytes
    write_asset(path, data, budget=4096)
    assert not path.exists(), "the whole file must not ship alongside its parts"
    m = _manifest(path)
    names = [p["path"] for p in m["parts"]]
    assert names == [
        "embeddings.bin.part-000.bin",
        "embeddings.bin.part-001.bin",
        "embeddings.bin.part-002.bin",
    ]
    for p in m["parts"]:
        part = tmp_path / p["path"]
        assert part.stat().st_size == p["size"] <= 4096
    assert b"".join((tmp_path / n).read_bytes() for n in names) == data


def test_read_asset_bytes_round_trips_both_shapes(tmp_path: Path) -> None:
    small, big = tmp_path / "a.json", tmp_path / "b.bin"
    write_asset(small, b"{}", budget=64)
    payload = b"\x00\x01" * 100
    write_asset(big, payload, budget=64)
    assert read_asset_bytes(small) == b"{}"
    assert read_asset_bytes(big) == payload


def test_read_asset_json_decodes_after_reassembly_across_multibyte_splits(tmp_path: Path) -> None:
    path = tmp_path / "pages-cleaned.json"
    doc = {"pages": [{"text": "é" * 50 + "✓" * 50} for _ in range(20)]}
    write_asset(path, json.dumps(doc, ensure_ascii=False).encode("utf-8"), budget=333)
    assert len(_manifest(path)["parts"]) > 1
    assert read_asset_json(path) == doc


def test_read_falls_back_to_a_plain_file_without_manifest(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text("[1]")
    assert read_asset_json(path) == [1]


def test_read_missing_asset_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_asset_bytes(tmp_path / "nope.json")


def test_read_rejects_a_part_that_does_not_match_the_manifest(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    write_asset(path, b"a" * 100, budget=40)
    (tmp_path / "x.bin.part-001.bin").write_bytes(b"b" * 34)
    with pytest.raises(ValueError, match="x.bin"):
        read_asset_bytes(path)


def test_rewrite_removes_stale_parts_and_restores_the_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    write_asset(path, b"a" * 100, budget=40)
    write_asset(path, b"a" * 10, budget=40)
    assert path.read_bytes() == b"a" * 10
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.bin", "x.bin.chunks.json"]
    write_asset(path, b"a" * 100, budget=40)
    write_asset(path, b"a" * 50, budget=40)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "x.bin.chunks.json", "x.bin.part-000.bin", "x.bin.part-001.bin",
    ]


def test_find_budget_violations_lists_every_oversize_file(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_bytes(b"a" * 10)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "big.bin").write_bytes(b"a" * 11)
    assert find_budget_violations([tmp_path], budget=10) == [(tmp_path / "sub" / "big.bin", 11)]


def test_find_budget_violations_skips_missing_roots(tmp_path: Path) -> None:
    assert find_budget_violations([tmp_path / "absent"], budget=10) == []


def test_find_manifest_errors_is_empty_for_a_consistent_tree(tmp_path: Path) -> None:
    write_asset(tmp_path / "a.bin", b"a" * 100, budget=40)
    write_asset(tmp_path / "b.json", b"[]", budget=40)
    assert find_manifest_errors([tmp_path]) == []


def test_find_manifest_errors_flags_stale_whole_file_and_drifted_parts(tmp_path: Path) -> None:
    write_asset(tmp_path / "a.bin", b"a" * 100, budget=40)
    (tmp_path / "a.bin").write_bytes(b"a" * 100)  # stale whole copy
    write_asset(tmp_path / "b.json", b"[]", budget=40)
    (tmp_path / "b.json").write_bytes(b"[1]")  # edited without the manifest
    errors = find_manifest_errors([tmp_path])
    assert any("a.bin" in e and "whole" in e for e in errors)
    assert any("b.json" in e for e in errors)


def test_read_rejects_part_paths_that_escape_the_asset_directory(tmp_path: Path) -> None:
    (tmp_path / "x.bin.chunks.json").write_text(json.dumps(
        {"name": "x.bin", "size": 1, "sha256": "", "parts": [{"path": "../x", "size": 1}]}
    ))
    with pytest.raises(ValueError, match="part path"):
        read_asset_bytes(tmp_path / "x.bin")
