"""End-to-end: ``pursue ingest run --dry-run`` from a second git worktree
is refused when the worktree is not this install's own (R7C.4, acceptance
criterion 5).

A real ``git worktree add`` checks out a second, independent working tree
sharing the first's ``.git`` -- physically separate files, not a symlink.
Before ``pursue_index.paths.repo_root()`` this exact shape (Release 7's
reported bug) resolved every default data path against the checkout the
venv's editable install happened to be pinned to, not the worktree the
process was actually standing in. This test invokes the real installed
``pursue`` console script -- not a Python import, not ``CliRunner`` -- so
nothing about the test harness can paper over a wrong resolution.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SHA = "a1b2c3d4e5f6" + "0" * 52  # 64 hex chars


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _pursue_bin() -> Path:
    return Path(sys.executable).parent / "pursue"


def _build_base_fixture_repo(root: Path) -> None:
    """A pursue-index-shaped checkout with everything ``ingest run
    --from-diff --dry-run`` needs at its DEFAULT (unflagged) data paths."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")

    manifests_dir = root / "data" / "manifests"
    snapshots_dir = manifests_dir / "snapshots"
    snapshots_dir.mkdir(parents=True)
    (manifests_dir / "latest.json").write_text(
        json.dumps({"csv_sha256": "priorsha", "cards": []}), encoding="utf-8"
    )
    (snapshots_dir / f"{_SHA}.json").write_text(
        json.dumps({"csv_sha256": _SHA, "fetched_at": "2026-10-24T00:00:00Z", "cards": []}),
        encoding="utf-8",
    )

    diff_dir = root / "data" / "tranche-diffs"
    diff_dir.mkdir(parents=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(
        json.dumps({
            "tranche_sha256": _SHA,
            "summary": {"new_content": 1},
            "renames_confirmed": [],
            "new_content": [
                {"new_card_id": "newcard1", "title": "X", "asset_url": "https://x/a.pdf"},
            ],
            "quarantined": [],
            "restored_unchanged": [],
            "restored_modified": [],
            "field_only_changes": [],
        }),
        encoding="utf-8",
    )

    (root / "data" / "tranche-approval-log.jsonl").write_text(
        json.dumps({"tranche_sha256": _SHA}) + "\n", encoding="utf-8"
    )
    (root / "data" / "card-aliases.json").write_text(
        json.dumps({"aliases": []}), encoding="utf-8"
    )
    (root / "data" / "asset-bytes-registry.jsonl").write_text("", encoding="utf-8")

    _run(["git", "init", "-q", "-b", "main"], root)
    _run(["git", "config", "user.email", "test@example.com"], root)
    _run(["git", "config", "user.name", "Test"], root)
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-q", "-m", "initial"], root)


def test_dry_run_from_a_worktree_of_an_unrelated_checkout_is_refused(
    tmp_path: Path,
) -> None:
    """A worktree of some other pursue-index clone is not this install's
    checkout or one of its worktrees, so nothing is read or written there."""
    base_repo = tmp_path / "base-repo"
    base_repo.mkdir()
    _build_base_fixture_repo(base_repo)

    worktree = tmp_path / "second-worktree"
    add_result = _run(
        ["git", "worktree", "add", "-b", "second-worktree-branch", str(worktree), "main"],
        base_repo,
    )
    assert add_result.returncode == 0, add_result.stderr

    result = _run(
        [str(_pursue_bin()), "ingest", "run", "--tranche", _SHA, "--from-diff", "--dry-run"],
        worktree,
    )

    assert result.returncode != 0
    assert "not the installed checkout" in (result.stdout + result.stderr)
    assert str(worktree) not in result.stdout
    assert not (worktree / "data" / "ingest-worklist.txt").exists()
    assert not (base_repo / "data" / "ingest-worklist.txt").exists()
