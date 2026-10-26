"""The freshness gate refuses when it cannot show the checkout is current:
a configured remote whose ``origin/main`` ref is gone, or a checkout whose
last fetch is too old to mean anything."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from pursue_index.poll_freshness import (
    MAX_FETCH_AGE_SECONDS,
    PollCheckError,
    commits_behind_on_poll_paths,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _run(["git", "init", "-q", "-b", "main"], origin)
    _run(["git", "config", "user.email", "t@example.com"], origin)
    _run(["git", "config", "user.name", "T"], origin)
    (origin / "data").mkdir()
    (origin / "data" / "last-known-csv-sha.txt").write_text("abc\n")
    _run(["git", "add", "-A"], origin)
    _run(["git", "commit", "-q", "-m", "initial"], origin)
    clone = tmp_path / "clone"
    _run(["git", "clone", "-q", str(origin), str(clone)], tmp_path)
    return origin, clone


def _age_fetch_evidence(clone: Path, seconds: float) -> None:
    old = time.time() - seconds
    git = clone / ".git"
    for rel in ("FETCH_HEAD", "packed-refs", "refs/remotes/origin/main"):
        path = git / rel
        if path.exists():
            os.utime(path, (old, old))


def test_missing_origin_main_with_a_remote_configured_refuses(tmp_path: Path) -> None:
    _, clone = _origin_and_clone(tmp_path)
    _run(["git", "update-ref", "-d", "refs/remotes/origin/main"], clone)

    with pytest.raises(PollCheckError, match="origin/main"):
        commits_behind_on_poll_paths(clone)


def test_remote_under_another_name_refuses(tmp_path: Path) -> None:
    _, clone = _origin_and_clone(tmp_path)
    _run(["git", "remote", "rename", "origin", "upstream"], clone)

    with pytest.raises(PollCheckError, match="origin/main"):
        commits_behind_on_poll_paths(clone)


def test_a_stale_fetch_refuses_and_says_to_fetch(tmp_path: Path) -> None:
    _, clone = _origin_and_clone(tmp_path)
    _age_fetch_evidence(clone, MAX_FETCH_AGE_SECONDS + 3600)

    with pytest.raises(PollCheckError, match="git fetch"):
        commits_behind_on_poll_paths(clone)


def test_a_recent_fetch_passes(tmp_path: Path) -> None:
    _, clone = _origin_and_clone(tmp_path)
    _age_fetch_evidence(clone, MAX_FETCH_AGE_SECONDS + 3600)
    _run(["git", "fetch", "-q", "origin"], clone)

    assert commits_behind_on_poll_paths(clone) == 0
