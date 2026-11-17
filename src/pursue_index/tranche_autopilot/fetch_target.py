"""Whether the checkout is the repo the freshness recheck fetches.

The fetch target is a slug the autopilot is given (``child_env.INDEX_SLUG``
unless its config or CLI says otherwise), never one read from git config.
This module only refuses: a GitHub ``origin`` naming another repo, or a
local ``insteadOf`` that would rewrite the fetch URL, means the checkout is
not the index (or its config is redirecting the fetch), so the run stops.
"""

from __future__ import annotations

import re
from pathlib import Path

from pursue_index.tranche_autopilot.child_env import fetch_url
from pursue_index.tranche_autopilot.gitops import GitError, local_url_rewrites, origin_url
from pursue_index.tranche_autopilot.result import repo_slug
from pursue_index.tranche_autopilot.runner import Runner

__all__ = ["fetch_target_problem", "valid_slug"]

_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def valid_slug(slug: str) -> bool:
    """``owner/name`` with neither part ``.``, ``..`` or only dots."""
    if not _SLUG.fullmatch(slug) or ".." in slug:
        return False
    return all(part.strip(".") for part in slug.split("/"))


def fetch_target_problem(runner: Runner, repo: Path, expected: str) -> str | None:
    """Why fetching ``expected`` into this checkout must be refused, or ``None``."""
    url = origin_url(runner, repo)
    found = repo_slug(url) if url else None
    if found is not None and found.casefold() != expected.casefold():
        return (f"origin names {found}, not the index {expected}: this checkout is not "
                "the index (set --expected-repo to promote another one)")
    try:
        rewrites = local_url_rewrites(runner, repo)
    except GitError as exc:
        return f"cannot read the checkout's url rewrites: {exc}"
    target = fetch_url(expected)
    hits = sorted(key for key, prefix in rewrites if prefix and target.startswith(prefix))
    if hits:
        return (f"the checkout's config rewrites the fetch URL of {expected} "
                f"({', '.join(hits)}); remove the insteadOf to run the autopilot")
    return None
