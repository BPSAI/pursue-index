#!/usr/bin/env python3
"""Validate the workflow_dispatch inputs before any step uses them.

Reads ``BASE_URL`` (and optionally ``MAX_WAIT_SECS`` and its ceiling
``MAX_WAIT_SECS_CAP``) from the environment --
never from a shell-interpolated expression -- so a crafted input cannot inject
commands. ``BASE_URL`` must be ``https://`` + an allowlisted host, with no
credentials, port, query, fragment, or path beyond ``/``.

Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"pursueindex.com", "www.pursueindex.com"})


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
    cap = os.environ.get("MAX_WAIT_SECS_CAP")
    if cap is not None:
        if not re.fullmatch(r"[0-9]+", cap):
            print(f"::error::MAX_WAIT_SECS_CAP {cap!r} must be a non-negative integer", file=sys.stderr)
            return 1
        if wait is not None and int(wait) > int(cap):
            print(f"::error::max_wait_secs {wait} exceeds the {cap}s that fits the job timeout "
                  f"(after the build wait, the deploy-stamp wait and the failure-issue step); "
                  f"use {cap} or less", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
