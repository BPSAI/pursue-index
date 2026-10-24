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

import getpass
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pursue_index.safe_git import GitUnavailableError, run_git

__all__ = [
    "MIN_REASON_LENGTH",
    "POLL_WRITTEN_PATHS",
    "BehindPollerError",
    "PollCheckError",
    "commits_behind_on_poll_paths",
    "refuse_if_behind",
    "require_reason",
]

_ORIGIN_MAIN = "refs/remotes/origin/main"

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


MIN_REASON_LENGTH = 12


class PollCheckError(RuntimeError):
    """The freshness check could not be completed; the gate must refuse."""


def require_reason(reason: str | None) -> str:
    """The stripped override reason, or ``ValueError`` if it is too thin."""
    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_LENGTH:
        raise ValueError(
            f"--reason must be at least {MIN_REASON_LENGTH} characters "
            "(after trimming whitespace)"
        )
    return cleaned


def commits_behind_on_poll_paths(repo_root: Path) -> int:
    """Commits on ``origin/main`` touching ``POLL_WRITTEN_PATHS`` that
    ``HEAD`` lacks.

    Returns 0 only when the checkout has no ``origin/main`` ref (no remote
    configured). Every other failure -- git missing, a timeout, a non-zero
    exit, unparseable output -- raises :class:`PollCheckError`.
    """
    try:
        ref = run_git(repo_root, "rev-parse", "--verify", "--quiet", _ORIGIN_MAIN)
        if ref.returncode == 1 and not ref.stderr.strip():
            return 0
        if ref.returncode != 0:
            raise PollCheckError(_git_failure("rev-parse", ref))
        result = run_git(
            repo_root, "rev-list", "--count", f"HEAD..{_ORIGIN_MAIN}",
            "--", *POLL_WRITTEN_PATHS,
        )
    except GitUnavailableError as exc:
        raise PollCheckError(str(exc)) from exc
    if result.returncode != 0:
        raise PollCheckError(_git_failure("rev-list", result))
    output = result.stdout.strip()
    if not output.isdigit():
        raise PollCheckError(f"git rev-list returned unexpected output: {output!r}")
    return int(output)


def _git_failure(step: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = result.stderr.strip() or f"exit {result.returncode}"
    return f"git {step} failed: {detail}"


def _record_allow_behind(
    audit_log: Path, *, commit_count: int, reason: str, tranche_sha: str | None,
) -> None:
    row = {
        "at": datetime.now(UTC).isoformat(),
        "user": getpass.getuser(),
        "tranche_sha256": tranche_sha,
        "commit_count": commit_count,
        "reason": reason,
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def refuse_if_behind(
    repo_root: Path, *, allow_behind: bool, reason: str | None, audit_log: Path,
    tranche_sha: str | None = None,
) -> None:
    """Raise :class:`BehindPollerError` unless caught up or overridden.

    A failed check raises :class:`PollCheckError` regardless of
    ``allow_behind``: an override acknowledges known staleness, not an
    unknown state. ``reason`` is validated with :func:`require_reason`
    before anything is recorded.
    """
    count = commits_behind_on_poll_paths(repo_root)
    if count == 0:
        return
    if not allow_behind:
        raise BehindPollerError(count)
    _record_allow_behind(
        audit_log, commit_count=count, reason=require_reason(reason),
        tranche_sha=tranche_sha,
    )
