"""Local git operations for the autopilot: read the tree, make one commit.

Only reads (status, branch, HEAD) and a local ``add``/``commit``. Publishing
the commit is the operator's step, spelled out as text in the result.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pursue_index.tranche_autopilot.runner import Runner

__all__ = ["GitError", "changed_paths", "commit_paths", "current_branch", "head_sha",
           "is_clean", "path_summary"]

_GIT_TIMEOUT = 120.0
_PATH_LIST_CAP = 200


class GitError(RuntimeError):
    """A git command failed."""


def _git(runner: Runner, repo: Path, *args: str) -> str:
    result = runner(["git", *args], cwd=repo, timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise GitError(f"git {args[0]} failed: {detail}")
    return result.stdout


def changed_paths(runner: Runner, repo: Path) -> list[str]:
    """Every modified, added, deleted or untracked path (``status -z``)."""
    out = _git(runner, repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # a rename/copy carries its source as the next entry
            paths.append(entries[i])
            i += 1
    return sorted(set(paths))


def is_clean(runner: Runner, repo: Path) -> bool:
    return not changed_paths(runner, repo)


def current_branch(runner: Runner, repo: Path) -> str | None:
    """The checked-out branch, or ``None`` on a detached HEAD."""
    result = runner(["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                    cwd=repo, timeout=_GIT_TIMEOUT)
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else None


def head_sha(runner: Runner, repo: Path) -> str:
    return _git(runner, repo, "rev-parse", "HEAD").strip()


def commit_paths(runner: Runner, repo: Path, paths: list[str], message: str) -> str:
    """Stage exactly ``paths`` and commit them; returns the new HEAD sha."""
    _git(runner, repo, "add", "--all", "--", *paths)
    _git(runner, repo, "commit", "--quiet", "-m", message)
    return head_sha(runner, repo)


def path_summary(paths: list[str]) -> dict[str, object]:
    """Count, per-top-level-directory counts and a capped path list."""
    tops = Counter(p.split("/", 1)[0] if "/" in p else "." for p in paths)
    return {
        "count": len(paths),
        "by_top_dir": dict(sorted(tops.items())),
        "paths": paths[:_PATH_LIST_CAP],
        "truncated": len(paths) > _PATH_LIST_CAP,
    }
