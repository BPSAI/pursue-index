"""``scripts/chunk_public_assets.py``: split any over-budget payload in place."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from pursue_index.release.chunked_asset import (
    find_budget_violations,
    find_manifest_errors,
    manifest_path,
    read_asset_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "chunk_public_assets.py"


def _mod():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("chunk_public_assets", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sweep_splits_every_oversize_file_losslessly(tmp_path: Path) -> None:
    big = bytes(range(256)) * 10
    (tmp_path / "embeddings.bin").write_bytes(big)
    (tmp_path / "small.json").write_bytes(b"[]")
    assert _mod().main(["--root", str(tmp_path), "--budget-bytes", "1000"]) == 0
    assert find_budget_violations([tmp_path], budget=1000) == []
    assert find_manifest_errors([tmp_path]) == []
    assert read_asset_bytes(tmp_path / "embeddings.bin") == big
    # A file already within budget is left exactly as it was.
    assert not manifest_path(tmp_path / "small.json").exists()


def test_sweep_skips_parts_and_manifests(tmp_path: Path) -> None:
    (tmp_path / "x.bin").write_bytes(b"a" * 3000)
    mod = _mod()
    mod.main(["--root", str(tmp_path), "--budget-bytes", "1000"])
    before = sorted(p.name for p in tmp_path.iterdir())
    mod.main(["--root", str(tmp_path), "--budget-bytes", "1000"])
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_named_assets_get_a_manifest_even_when_within_budget(tmp_path: Path) -> None:
    (tmp_path / "pages.json").write_bytes(b"[1]")
    assert _mod().main(
        ["--root", str(tmp_path), "--budget-bytes", "1000", "pages.json"]
    ) == 0
    assert (tmp_path / "pages.json").read_bytes() == b"[1]"
    assert manifest_path(tmp_path / "pages.json").exists()


def test_named_asset_already_chunked_is_republished_from_its_parts(tmp_path: Path) -> None:
    (tmp_path / "x.bin").write_bytes(b"a" * 3000)
    mod = _mod()
    mod.main(["--root", str(tmp_path), "--budget-bytes", "1000", "x.bin"])
    assert mod.main(["--root", str(tmp_path), "--budget-bytes", "1000", "x.bin"]) == 0
    assert read_asset_bytes(tmp_path / "x.bin") == b"a" * 3000


def test_sweep_refuses_to_chunk_nested_files_and_fails(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """The Worker only reassembles /data/<name>; a nested oversize file is
    left untouched and the sweep exits non-zero instead of chunking it."""
    nested = tmp_path / "thumbs" / "big.bin"
    nested.parent.mkdir()
    nested.write_bytes(b"a" * 3000)
    (tmp_path / "top.bin").write_bytes(b"b" * 3000)
    rc = _mod().main(["--root", str(tmp_path), "--budget-bytes", "1000"])
    assert rc == 1
    assert nested.read_bytes() == b"a" * 3000
    assert not manifest_path(nested).exists()
    assert list(nested.parent.iterdir()) == [nested]
    assert "thumbs" in capsys.readouterr().err
    # The top-level file is still chunked.
    assert read_asset_bytes(tmp_path / "top.bin") == b"b" * 3000
    assert not (tmp_path / "top.bin").exists()


def test_named_asset_must_be_top_level(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.json").write_bytes(b"[]")
    assert _mod().main(["--root", str(tmp_path), "sub/x.json"]) == 1
    assert not manifest_path(tmp_path / "sub" / "x.json").exists()
