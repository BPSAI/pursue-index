"""Print ``true`` unless every changed path is on the skip-safe allowlist.

Reads changed paths on stdin: NUL-separated (``git -c core.quotePath=false
diff --name-only -z``, the form the workflow uses, which never quotes), or one
per line.
Used by the ``pytest`` job in ``.github/workflows/tests.yml``, which must
report on every pull request because branch protection requires it, but
only needs to run the suite when code or tests changed.

Fails safe: empty input (no diff could be computed) prints ``true``, and so
does any C-quoted path (git's default output for a non-ASCII name), since a
quoted path can't be matched against the allowlist. Any path not on the
allowlist also prints ``true``.

The workflow runs the BASE branch's copy of this file, so a pull request
cannot edit it to skip its own suite.
"""

from __future__ import annotations

import sys

# Allowlist: only these paths never need the suite. Everything else, including
# any new top-level directory, runs it.
SKIP_SAFE_PREFIXES = ("data/", "web/public/data/", "web/src/data/", "docs/")


def needs_tests(path: str) -> bool:
    if path.startswith('"'):
        return True
    if path.startswith(SKIP_SAFE_PREFIXES):
        return False
    if path.endswith(".md") and "/" not in path:
        return False
    return True


def main() -> int:
    # Raw bytes, decoded leniently: an undecodable name must never crash this
    # (a crash leaves the workflow's `code` empty, which it treats as true).
    data = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
    parts = data.split("\0") if "\0" in data else data.splitlines()
    paths = [p.strip() for p in parts if p.strip()]
    print("true" if not paths or any(needs_tests(p) for p in paths) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
