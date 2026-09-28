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
    write_asset(tmp_path / "pages.json", b"[]", budget=1024)
    (tmp_path / "pages.json").write_bytes(b"[1, 2]")
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 1
    assert "pages.json" in res.stderr


def test_gate_passes_a_chunked_tree(tmp_path: Path) -> None:
    write_asset(tmp_path / "big.bin", b"a" * 4096, budget=1024)
    res = _run("--budget-bytes", "1024", str(tmp_path))
    assert res.returncode == 0, res.stderr


def test_committed_public_tree_is_within_the_deploy_budget() -> None:
    """The tree Cloudflare will upload: every file <= 24 MiB, manifests sound."""
    res = _run(str(REPO_ROOT / "web" / "public"))
    assert res.returncode == 0, res.stderr
