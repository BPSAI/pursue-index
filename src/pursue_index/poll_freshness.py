"""Refuse an ingest command against a checkout behind the poller.

``scripts/poll_pursue.py`` is the only writer of ``data/last-known-csv-
sha.txt``, ``data/manifests/snapshots/`` and ``data/raw/csv/`` -- the
inputs a tranche approval or run depends on. A checkout whose ``HEAD`` is
behind ``origin/main`` on those paths has stale inputs even though the
files on disk look present, which is exactly how Release 7 shipped six
poll commits behind. ``ingest approve``/``ingest run`` call
``refuse_if_behind`` before doing anything else; ``--allow-behind
--reason`` is the audited escape hatch.

This only ever reads the last-fetched ``origin/main`` -- it never runs
``git fetch`` itself, so it can't silently pull network state into a
gate check.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "POLL_WRITTEN_PATHS",
    "BehindPollerError",
    "commits_behind_on_poll_paths",
    "refuse_if_behind",
]

# R7C.31 adds its paths here.
POLL_WRITTEN_PATHS: tuple[str, ...] = (
    "data/last-known-csv-sha.txt",
    "data/manifests/snapshots/",
    "data/raw/csv/",
)


class BehindPollerError(RuntimeError):
    def __init__(self, commit_count: int) -> None:
        self.commit_count = commit_count
        super().__init__(
            f"checkout is {commit_count} commit(s) behind origin/main on "
            f"poll-written paths ({', '.join(POLL_WRITTEN_PATHS)})"
        )


def commits_behind_on_poll_paths(repo_root: Path) -> int:
    """Commits on ``origin/main`` touching ``POLL_WRITTEN_PATHS`` that
    ``HEAD`` lacks. Returns 0 if there is no ``origin/main`` ref (e.g. no
    remote configured) so a bare local checkout is never refused on this
    basis."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-list", "--count",
         "HEAD..origin/main", "--", *POLL_WRITTEN_PATHS],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return 0
    output = result.stdout.strip()
    return int(output) if output.isdigit() else 0


def _record_allow_behind(audit_log: Path, *, commit_count: int, reason: str) -> None:
    row = {
        "at": datetime.now(UTC).isoformat(),
        "commit_count": commit_count,
        "reason": reason,
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def refuse_if_behind(
    repo_root: Path, *, allow_behind: bool, reason: str | None, audit_log: Path,
) -> None:
    """Raise :class:`BehindPollerError` unless caught up or overridden.

    ``allow_behind`` with no ``reason`` is a caller bug -- the CLI layer
    is responsible for requiring a non-empty ``--reason`` alongside
    ``--allow-behind``; this function records whatever reason it is given.
    """
    count = commits_behind_on_poll_paths(repo_root)
    if count == 0:
        return
    if not allow_behind:
        raise BehindPollerError(count)
    _record_allow_behind(audit_log, commit_count=count, reason=reason or "")
