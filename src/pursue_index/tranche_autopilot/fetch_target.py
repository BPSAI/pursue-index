"""Whether the checkout is the repo the freshness recheck fetches.

The fetch target is a slug the autopilot is given (``child_env.INDEX_SLUG``
unless its config or CLI says otherwise), never one read from git config.
This module only refuses: a GitHub ``origin`` naming another repo, a local
``insteadOf`` that would rewrite the fetch URL, or a local ``http.*`` key that
applies to it (a proxy, TLS or header setting) means the checkout is not the
index or its config is redirecting or reshaping the fetch, so the run stops.
"""

from __future__ import annotations

import re
from pathlib import Path

from pursue_index.tranche_autopilot.child_env import fetch_url
from pursue_index.tranche_autopilot.gitops import (
    GitError,
    local_http_keys,
    local_url_rewrites,
    origin_url,
)
from pursue_index.tranche_autopilot.result import repo_slug
from pursue_index.tranche_autopilot.runner import Runner
from pursue_index.tranche_autopilot.urlmatch import config_url_applies

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
        http_keys = local_http_keys(runner, repo)
    except GitError as exc:
        return f"cannot read the checkout's fetch config: {exc}"
    target = fetch_url(expected)
    # An empty prefix matches every URL (git prepends the base); a blank one is
    # refused too, failing closed.
    hits = sorted(key for key, prefix in rewrites
                  if not prefix.strip() or target.startswith(prefix))
    if hits:
        return (f"the checkout's config rewrites the fetch URL of {expected} "
                f"({', '.join(hits)}); remove the insteadOf to run the autopilot")
    applied = sorted(key for key in http_keys if _http_key_applies(key, target))
    if applied:
        return (f"the checkout's config sets http options for the fetch of {expected} "
                f"({', '.join(applied)}); remove them to run the autopilot")
    return None


def _http_key_applies(key: str, target: str) -> bool:
    """``http.<var>`` applies to every URL; ``http.<url>.<var>`` to the URLs git
    matches it against (URL-specific keys win over the fetch's ``-c`` ones)."""
    config_url = key[len("http."):].rpartition(".")[0]
    return not config_url or config_url_applies(config_url, target)
