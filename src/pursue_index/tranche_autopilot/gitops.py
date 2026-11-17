"""Local git operations for the autopilot: read the tree, make one commit.

Only reads (status, branch, HEAD) and a local ``add``/``commit``. Publishing
the commit is the operator's step, spelled out as text in the result.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pursue_index.tranche_autopilot.runner import Runner

__all__ = ["GitError", "changed_paths", "commit_paths", "current_branch", "head_sha",
           "is_clean", "local_credential_keys", "local_http_keys", "local_url_rewrites",
           "modified_tracked_paths", "origin_url", "path_summary", "untracked_paths"]

_GIT_TIMEOUT = 120.0
# `git config --show-scope` arrived in git 2.26; older git rejects the option.
_SHOW_SCOPE_MIN_GIT = "2.26"
_PATH_LIST_CAP = 200


class GitError(RuntimeError):
    """A git command failed."""


def _git(runner: Runner, repo: Path, *args: str) -> str:
    result = runner(["git", *args], cwd=repo, timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise GitError(f"git {args[0]} failed: {detail}")
    return result.stdout


def _status(runner: Runner, repo: Path) -> list[tuple[str, str]]:
    """``(XY status, path)`` for every change, untracked files included."""
    out = _git(runner, repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = out.split("\0")
    rows: list[tuple[str, str]] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        rows.append((entry[:2], entry[3:]))
        # A rename/copy carries its source as the next entry, whether it is
        # staged (X column) or only in the worktree (Y column, e.g. " R").
        if "R" in entry[:2] or "C" in entry[:2]:
            rows.append((entry[:2], entries[i]))
            i += 1
    return rows


def changed_paths(runner: Runner, repo: Path) -> list[str]:
    """Every modified, added, deleted or untracked path."""
    return sorted({path for _, path in _status(runner, repo)})


def untracked_paths(runner: Runner, repo: Path) -> list[str]:
    """Only the new, untracked paths."""
    return sorted({path for xy, path in _status(runner, repo) if xy == "??"})


def modified_tracked_paths(runner: Runner, repo: Path) -> list[str]:
    """Tracked paths with uncommitted changes (untracked files excluded)."""
    return sorted({path for xy, path in _status(runner, repo) if xy != "??"})


def origin_url(runner: Runner, repo: Path) -> str | None:
    result = runner(["git", "remote", "get-url", "origin"], cwd=repo, timeout=_GIT_TIMEOUT)
    url = result.stdout.strip()
    return url if result.returncode == 0 and url else None


def _local_config(runner: Runner, repo: Path, pattern: str) -> list[tuple[str, str]]:
    """``(key, value)`` for every key matching ``pattern`` in the checkout's own
    config (local and worktree scope, includes followed). System and global
    config are left out: the fetch ignores them. Keys come back lowercased
    except for a subsection, which git keeps as written."""
    result = runner(["git", "config", "--show-scope", "--includes", "--get-regexp",
                     pattern], cwd=repo, timeout=_GIT_TIMEOUT)
    if result.returncode == 1:  # no match
        return []
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        if "unknown option" in detail and "show-scope" in detail:
            raise GitError(f"git {_SHOW_SCOPE_MIN_GIT} or newer is required to read the "
                           "checkout's config by scope (git config --show-scope); "
                           "upgrade git to run the autopilot")
        raise GitError(f"git config failed: {detail}")
    entries = []
    for line in result.stdout.splitlines():
        scope, _, entry = line.partition("\t")
        key, _, value = entry.partition(" ")
        if scope in ("local", "worktree"):
            entries.append((key, value))
    return entries


def local_url_rewrites(runner: Runner, repo: Path) -> list[tuple[str, str]]:
    """``(key, prefix)`` for every local ``url.<base>.insteadOf``."""
    return _local_config(runner, repo, r"^url\..*\.insteadof$")


def local_http_keys(runner: Runner, repo: Path) -> list[str]:
    """Every local ``http.*`` key, general (``http.<var>``) or URL-scoped
    (``http.<url>.<var>``)."""
    return [key for key, _value in _local_config(runner, repo, r"^http\.")]


def local_credential_keys(runner: Runner, repo: Path) -> list[str]:
    """Every local ``credential.*`` key, general (``credential.<var>``) or
    URL-scoped (``credential.<url>.<var>``)."""
    return [key for key, _value in _local_config(runner, repo, r"^credential\.")]


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
