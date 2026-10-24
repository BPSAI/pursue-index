"""The coverage gate's presence check understands chunked payloads.

A payload over the deploy budget ships as ``<name>.chunks.json`` plus parts
instead of one file. Presence is the production predicate ``asset_exists``;
a manifest whose parts are missing or drifted is caught at load time, where
``json_loader`` reads through the verifying chunk reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.release.chunked_asset import asset_exists, manifest_path, write_asset
from tests.support.payload_coverage import json_loader

_DOC = json.dumps({"k": list(range(200))}).encode()


def test_monolith_is_present(tmp_path: Path) -> None:
    (tmp_path / "pages.json").write_bytes(_DOC)
    assert asset_exists(tmp_path / "pages.json")


def test_neither_monolith_nor_manifest_is_absent(tmp_path: Path) -> None:
    assert not asset_exists(tmp_path / "pages.json")


def test_valid_chunked_asset_exists(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    assert len(parts) == 2 and not target.exists()
    assert asset_exists(target)


def test_chunked_asset_with_missing_part_fails_to_load(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    parts[1].unlink()
    assert manifest_path(target).is_file()
    with pytest.raises(FileNotFoundError):
        json_loader(tmp_path)("pages.json")


def test_chunked_asset_with_drifted_part_fails_to_load(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    parts[0].write_bytes(parts[0].read_bytes()[:-1] + b"X")
    with pytest.raises(ValueError, match="sha256"):
        json_loader(tmp_path)("pages.json")
