"""Fail-closed deploy gate: no static asset over the 24 MiB budget.

``scripts/check_asset_budget.py`` is what ``make ship-ready`` and the
release-gate workflow run. It exits non-zero when any file under the given
roots exceeds the budget or a chunk manifest disagrees with its parts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pursue_index.release.chunked_asset import write_asset

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_asset_budget.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )


def test_gate_fails_on_an_oversize_file(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"a" * 2048)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    assert "big.bin" in res.stderr


def test_gate_fails_on_an_inconsistent_manifest(tmp_path: Path) -> None:
    write_asset(tmp_path / "data" / "pages.json", b"[]", budget=1024)
    (tmp_path / "data" / "pages.json").write_bytes(b"[1, 2]")
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    assert "pages.json" in res.stderr


def test_gate_passes_a_chunked_tree(tmp_path: Path) -> None:
    write_asset(tmp_path / "data" / "big.bin", b"a" * 4096, budget=1024)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 0, res.stderr


def test_committed_public_tree_is_within_the_deploy_budget() -> None:
    """The tree Cloudflare will upload: every file <= 24 MiB, manifests sound."""
    res = _run(str(REPO_ROOT / "web" / "public"))
    assert res.returncode == 0, res.stderr


def test_gate_fails_on_oversize_file_outside_top_level_data_with_a_clear_message(
    tmp_path: Path,
) -> None:
    """Only /data/<name> is reassembled by the Worker, so an oversize file
    anywhere else cannot be chunked: the gate fails and says so."""
    nested = tmp_path / "data" / "thumbs" / "big.bin"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"a" * 2048)
    (tmp_path / "og.png").write_bytes(b"a" * 2048)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    for name in ("thumbs/big.bin", "og.png"):
        line = next(ln for ln in res.stderr.splitlines() if name in ln)
        assert "cannot be chunked" in line and "top-level data/" in line


def test_gate_fails_on_a_chunk_manifest_outside_top_level_data(tmp_path: Path) -> None:
    write_asset(tmp_path / "data" / "sub" / "x.bin", b"a" * 4096, budget=1024)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    assert "x.bin.chunks.json" in res.stderr and "top-level data/" in res.stderr


def test_gate_points_top_level_oversize_files_at_the_chunker(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "big.json").write_bytes(b"a" * 2048)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    line = next(ln for ln in res.stderr.splitlines() if "big.json" in ln)
    assert "chunk_public_assets.py" in line
