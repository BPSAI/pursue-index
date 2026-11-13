"""ship-ready stamps every release with a commit anyone can check out.

``build-commit`` runs before any builder and records the code commit, refusing uncommitted
code or a commit not on the published branch. ``stamp`` writes
data/build-stamp.json after the last data write, and ship-ready ends by
verifying the stamp, its commit included.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_IDENT = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def _dry(target: str) -> list[str]:
    out = subprocess.run(["make", "-C", str(ROOT), "-n", target, "PYTHON=python3"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _at(lines: list[str], needle: str) -> int:
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert hits, needle
    return hits[0]


def test_ship_ready_records_the_commit_before_building_and_stamps_last() -> None:
    lines = _dry("ship-ready")
    record = _at(lines, "pursue-build-commit")
    assert _at(lines, "check_release_completeness.py") < record
    assert record < _at(lines, "build_search_data.py")  # before every builder
    stamp = _at(lines, "build_stamp.py write")
    assert _at(lines, "runbook_snapshot_rotate.py") < stamp < _at(lines, "npm run build")
    last = [ln for ln in lines if "build_stamp.py" in ln][-1]
    assert "verify" in last and "--require" in last and "--public-ref origin/main" in last


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *_IDENT, *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    """A git repo with this Makefile, the stamp script, one bundle file, and
    origin/main at its first commit."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "data" / "manifests").mkdir(parents=True)
    shutil.copy(ROOT / "Makefile", repo / "Makefile")
    shutil.copy(ROOT / "scripts" / "build_stamp.py", repo / "scripts" / "build_stamp.py")
    (repo / "data" / "manifests" / "latest.json").write_text("{}")
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def _make(repo: Path, *targets: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["make", "-C", str(repo), *targets, f"PYTHON={sys.executable}"],
                          capture_output=True, text=True, timeout=60)


def test_a_release_built_from_published_code_is_stamped_with_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    (repo / "data" / "manifests" / "latest.json").write_text('{"cards": 1}')  # a data write
    out = _make(repo, "build-commit", "stamp")
    assert out.returncode == 0, out.stderr
    stamp = json.loads((repo / "data" / "build-stamp.json").read_text())
    assert stamp["builder_commit"] == head


def test_uncommitted_code_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "scripts" / "local.py").write_text("print(1)\n")
    out = _make(repo, "build-commit")
    assert out.returncode != 0
    assert "uncommitted code" in out.stderr


def test_a_commit_not_on_the_published_branch_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "local only")
    out = _make(repo, "build-commit")
    assert out.returncode != 0
    assert "not on origin/main" in out.stderr


def test_a_commit_made_during_the_build_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _make(repo, "build-commit").returncode == 0
    _git(repo, "commit", "-q", "--allow-empty", "-m", "mid-build")
    out = _make(repo, "stamp")
    assert out.returncode != 0
    assert "HEAD moved" in out.stderr
    assert not (repo / "data" / "build-stamp.json").exists()
