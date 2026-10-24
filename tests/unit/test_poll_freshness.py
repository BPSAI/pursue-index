"""``pursue_index.poll_freshness`` -- refuse an ingest command against a
checkout behind the poller (R7C.4 / #169-adjacent).

Release 7 shipped from a main checkout six poll commits behind
``origin/main``: the tranche-diff/snapshot inputs on disk looked present
but were stale. ``commits_behind_on_poll_paths`` counts commits
``origin/main`` carries beyond ``HEAD`` that touch ``POLL_WRITTEN_PATHS``
(never fetching -- only reading the last-fetched ref), and
``refuse_if_behind`` turns that into a refusal unless the operator passes
an explicit, audited override.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pursue_index.poll_freshness import (
    POLL_WRITTEN_PATHS,
    BehindPollerError,
    commits_behind_on_poll_paths,
    refuse_if_behind,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _git_init_with_commit(root: Path, *, relpath: str, content: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], root)
    _run(["git", "config", "user.email", "test@example.com"], root)
    _run(["git", "config", "user.name", "Test"], root)
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-q", "-m", "initial"], root)


def _clone(src: Path, dst: Path) -> None:
    _run(["git", "clone", "-q", str(src), str(dst)], src.parent)


def _commit_poll_path_change(root: Path, *, relpath: str, content: str) -> None:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-q", "-m", "poll update"], root)


def test_poll_written_paths_covers_the_known_poller_outputs() -> None:
    assert "data/last-known-csv-sha.txt" in POLL_WRITTEN_PATHS
    assert "data/manifests/snapshots/" in POLL_WRITTEN_PATHS
    assert "data/raw/csv/" in POLL_WRITTEN_PATHS


def test_commits_behind_is_zero_when_no_origin_remote(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    _git_init_with_commit(repo, relpath="data/last-known-csv-sha.txt", content="abc\n")

    assert commits_behind_on_poll_paths(repo) == 0


def test_commits_behind_is_zero_when_up_to_date(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin, relpath="data/last-known-csv-sha.txt", content="abc\n")
    clone = tmp_path / "clone"
    _clone(origin, clone)

    assert commits_behind_on_poll_paths(clone) == 0


def test_commits_behind_counts_poll_path_commits_on_origin_main(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin, relpath="data/last-known-csv-sha.txt", content="abc\n")
    clone = tmp_path / "clone"
    _clone(origin, clone)

    _commit_poll_path_change(origin, relpath="data/last-known-csv-sha.txt", content="def\n")
    _commit_poll_path_change(origin, relpath="data/manifests/snapshots/x.json", content="{}\n")
    _run(["git", "fetch", "-q", "origin"], clone)

    assert commits_behind_on_poll_paths(clone) == 2


def test_commits_behind_ignores_commits_outside_poll_paths(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin, relpath="data/last-known-csv-sha.txt", content="abc\n")
    clone = tmp_path / "clone"
    _clone(origin, clone)

    _commit_poll_path_change(origin, relpath="README.md", content="unrelated change\n")
    _run(["git", "fetch", "-q", "origin"], clone)

    assert commits_behind_on_poll_paths(clone) == 0


def test_refuse_if_behind_is_a_noop_when_caught_up(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    _git_init_with_commit(repo, relpath="data/last-known-csv-sha.txt", content="abc\n")
    audit_log = tmp_path / "audit.jsonl"

    refuse_if_behind(repo, allow_behind=False, reason=None, audit_log=audit_log)

    assert not audit_log.exists()


def test_refuse_if_behind_raises_naming_the_commit_count(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin, relpath="data/last-known-csv-sha.txt", content="abc\n")
    clone = tmp_path / "clone"
    _clone(origin, clone)
    _commit_poll_path_change(origin, relpath="data/last-known-csv-sha.txt", content="def\n")
    _run(["git", "fetch", "-q", "origin"], clone)
    audit_log = tmp_path / "audit.jsonl"

    with pytest.raises(BehindPollerError) as excinfo:
        refuse_if_behind(clone, allow_behind=False, reason=None, audit_log=audit_log)

    assert excinfo.value.commit_count == 1
    assert "1" in str(excinfo.value)
    assert not audit_log.exists()


def test_refuse_if_behind_with_allow_behind_writes_audit_row(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin, relpath="data/last-known-csv-sha.txt", content="abc\n")
    clone = tmp_path / "clone"
    _clone(origin, clone)
    _commit_poll_path_change(origin, relpath="data/last-known-csv-sha.txt", content="def\n")
    _run(["git", "fetch", "-q", "origin"], clone)
    audit_log = tmp_path / "audit.jsonl"

    refuse_if_behind(
        clone, allow_behind=True, reason="operator verified snapshot by hand", audit_log=audit_log
    )

    rows = [json.loads(line) for line in audit_log.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["commit_count"] == 1
    assert rows[0]["reason"] == "operator verified snapshot by hand"
