"""Refuse an ingest command against a checkout behind the poller.

The poll workflow (``scripts/poll_pursue.py`` and its snapshot job,
``scripts/poll_snapshot.py``) is the only writer of ``POLL_WRITTEN_PATHS``
-- the CSV sha and bytes, the manifest snapshots, the tranche diffs and the
tranche-ready records -- the inputs a tranche approval or run depends on. A checkout whose ``HEAD`` is
behind ``origin/main`` on those paths has stale inputs even though the
files on disk look present, which is exactly how Release 7 shipped six
poll commits behind. ``ingest approve``/``ingest run`` call
``refuse_if_behind`` before doing anything else; ``--allow-behind
--reason`` is the audited escape hatch.

This only ever reads the last-fetched ``origin/main`` -- it never runs
``git fetch`` itself, so it can't silently pull network state into a
gate check. Because of that, the check also refuses when it cannot show the
fetch is recent: a checkout that merely has not fetched would otherwise look
current.
"""

from __future__ import annotations

import getpass
import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from pursue_index.safe_git import GitUnavailableError, run_git

__all__ = [
    "MAX_FETCH_AGE_SECONDS",
    "MIN_REASON_LENGTH",
    "POLL_WRITTEN_PATHS",
    "BehindPollerError",
    "PollCheckError",
    "commits_behind_on_poll_paths",
    "refuse_if_behind",
    "require_reason",
]

_ORIGIN_MAIN = "refs/remotes/origin/main"
_LOG = logging.getLogger(__name__)

# The poller runs on a 6h cron; a fetch older than this proves nothing.
MAX_FETCH_AGE_SECONDS = 12 * 3600

# R7C.31: the snapshot job also commits the tranche diff and the
# tranche-ready record, both read by the approval that follows.
POLL_WRITTEN_PATHS: tuple[str, ...] = (
    "data/last-known-csv-sha.txt",
    "data/manifests/snapshots/",
    "data/raw/csv/",
    "data/tranche-diffs/",
    "data/tranche-ready/",
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


def _remote_names(repo_root: Path) -> list[str]:
    remotes = run_git(repo_root, "remote")
    if remotes.returncode != 0:
        raise PollCheckError(_git_failure("remote", remotes))
    return remotes.stdout.split()


def _require_recent_fetch(repo_root: Path) -> None:
    """Refuse unless ``origin/main`` was fetched within ``MAX_FETCH_AGE_SECONDS``.

    The evidence is the newest mtime among ``FETCH_HEAD`` (rewritten by every
    fetch, even one that changes nothing), ``packed-refs`` and the loose
    ``origin/main`` ref (both written by a clone).
    """
    common = run_git(repo_root, "rev-parse", "--git-common-dir")
    if common.returncode != 0 or not common.stdout.strip():
        raise PollCheckError(_git_failure("rev-parse --git-common-dir", common))
    git_dir = Path(common.stdout.strip())
    git_dir = git_dir if git_dir.is_absolute() else repo_root / git_dir
    stamps = [
        (git_dir / rel).stat().st_mtime
        for rel in ("FETCH_HEAD", "packed-refs", _ORIGIN_MAIN)
        if (git_dir / rel).is_file()
    ]
    if not stamps or time.time() - max(stamps) > MAX_FETCH_AGE_SECONDS:
        raise PollCheckError(
            f"origin/main has not been fetched in the last "
            f"{MAX_FETCH_AGE_SECONDS // 3600}h; run `git fetch origin` first"
        )


def commits_behind_on_poll_paths(repo_root: Path) -> int:
    """Commits on ``origin/main`` touching ``POLL_WRITTEN_PATHS`` that
    ``HEAD`` lacks.

    Returns 0 only for a checkout with no remote at all (a warning is
    logged). Every other failure -- git missing, a timeout, a non-zero exit,
    unparseable output, a remote configured but ``origin/main`` absent, or a
    fetch older than ``MAX_FETCH_AGE_SECONDS`` -- raises
    :class:`PollCheckError`.
    """
    try:
        ref = run_git(repo_root, "rev-parse", "--verify", "--quiet", _ORIGIN_MAIN)
        if ref.returncode == 1 and not ref.stderr.strip():
            remotes = _remote_names(repo_root)
            if remotes:
                raise PollCheckError(
                    f"remote(s) {', '.join(remotes)} configured but origin/main "
                    "is missing; run `git fetch origin`"
                )
            _LOG.warning("no remote configured; skipping the poll-freshness check")
            return 0
        if ref.returncode != 0:
            raise PollCheckError(_git_failure("rev-parse", ref))
        _require_recent_fetch(repo_root)
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
