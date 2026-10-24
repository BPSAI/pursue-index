"""The coverage gate's presence check understands chunked payloads.

A payload over the deploy budget ships as ``<name>.chunks.json`` plus parts
instead of one file. The presence check must accept that shape, and must
still fail for an asset with no monolith and no manifest, or with a manifest
whose parts are missing or drifted.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.release.chunked_asset import manifest_path, write_asset
from tests.support.payload_coverage import asset_is_present

_DOC = json.dumps({"k": list(range(200))}).encode()


def test_monolith_is_present(tmp_path: Path) -> None:
    (tmp_path / "pages.json").write_bytes(_DOC)
    assert asset_is_present(tmp_path / "pages.json")


def test_neither_monolith_nor_manifest_is_absent(tmp_path: Path) -> None:
    assert not asset_is_present(tmp_path / "pages.json")


def test_valid_chunked_asset_is_present(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    assert len(parts) == 2 and not target.exists()
    assert asset_is_present(target)


def test_chunked_asset_with_missing_part_is_absent(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    parts[1].unlink()
    assert manifest_path(target).is_file()
    assert not asset_is_present(target)


def test_chunked_asset_with_drifted_part_is_absent(tmp_path: Path) -> None:
    target = tmp_path / "pages.json"
    parts = write_asset(target, _DOC, budget=len(_DOC) // 2 + 1)
    parts[0].write_bytes(parts[0].read_bytes()[:-1] + b"X")
    assert not asset_is_present(target)
