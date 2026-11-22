#!/usr/bin/env python3
"""Validate the workflow_dispatch inputs before any step uses them.

Reads ``BASE_URL`` (and optionally ``MAX_WAIT_SECS``) from the environment --
never from a shell-interpolated expression -- so a crafted input cannot inject
commands. The ceiling for ``MAX_WAIT_SECS`` is derived here from the job's
budget, passed as ``JOB_TIMEOUT_MINUTES``, ``BUILD_WAIT_SECS``,
``STAMP_WAIT_SECS`` and ``FAILURE_ISSUE_MARGIN_SECS`` (all or none). ``BASE_URL`` must be ``https://`` + an allowlisted host, with no
credentials, port, query, fragment, or path beyond ``/``.

Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"pursueindex.com", "www.pursueindex.com"})
BUDGET_ENV = ("JOB_TIMEOUT_MINUTES", "BUILD_WAIT_SECS", "STAMP_WAIT_SECS", "FAILURE_ISSUE_MARGIN_SECS")


def wait_cap_secs(job_minutes: int, build_wait: int, stamp_wait: int, margin: int) -> int:
    """Seconds left for the verify wait once the job's other waits and margin are paid."""
    return job_minutes * 60 - build_wait - stamp_wait - margin


def validate(url: str) -> str | None:
    """Return an error message, or ``None`` when ``url`` is acceptable."""
    if not url or re.search(r"\s", url):
        return "empty or contains whitespace"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        return f"unparseable: {exc}"
    if parts.scheme != "https":
        return "scheme must be https"
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return "credentials are not allowed"
    if port is not None or ":" in parts.netloc:
        return "a port is not allowed"
    if (parts.hostname or "") not in ALLOWED_HOSTS:
        return f"host must be one of {sorted(ALLOWED_HOSTS)}"
    if parts.path not in ("", "/") or parts.query or parts.fragment or "?" in url or "#" in url:
        return "no path beyond '/', query or fragment is allowed"
    return None


def main(argv: list[str] | None = None) -> int:
    url = os.environ.get("BASE_URL", "")
    err = validate(url)
    if err:
        print(f"::error::BASE_URL {url!r} rejected: {err}", file=sys.stderr)
        return 1
    wait = os.environ.get("MAX_WAIT_SECS")
    if wait is not None and not re.fullmatch(r"[0-9]+", wait):
        print(f"::error::MAX_WAIT_SECS {wait!r} must be a non-negative integer", file=sys.stderr)
        return 1
    parts = {k: os.environ.get(k) for k in BUDGET_ENV}
    given = {k: v for k, v in parts.items() if v is not None}
    if given:
        for k, v in given.items():
            if not re.fullmatch(r"[0-9]+", v):
                print(f"::error::{k} {v!r} must be a non-negative integer", file=sys.stderr)
                return 1
        if len(given) != len(BUDGET_ENV):
            missing = ", ".join(k for k in BUDGET_ENV if k not in given)
            print(f"::error::the wait budget is incomplete; missing {missing}", file=sys.stderr)
            return 1
        cap = wait_cap_secs(*(int(parts[k]) for k in BUDGET_ENV))
        if cap < 0:
            print(f"::error::the job timeout ({parts['JOB_TIMEOUT_MINUTES']} min) is shorter than "
                  f"its build wait, deploy-stamp wait and failure-issue margin", file=sys.stderr)
            return 1
        if wait is not None and int(wait) > cap:
            print(f"::error::max_wait_secs {wait} exceeds the {cap}s that fits the job timeout "
                  f"(after the build wait, the deploy-stamp wait and the failure-issue step); "
                  f"use {cap} or less", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
