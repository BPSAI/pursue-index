"""Print ``true`` when any changed path needs the Python test suite, else ``false``.

Reads changed paths on stdin: NUL-separated (``git -c core.quotePath=false
diff --name-only -z``, the form the workflow uses, which never quotes), or one
per line.
Used by the ``pytest`` job in ``.github/workflows/tests.yml``, which must
report on every pull request because branch protection requires it, but
only needs to run the suite when code or tests changed.

Fails safe: empty input (no diff could be computed) prints ``true``, and so
does any C-quoted path (git's default output for a non-ASCII name), since a
quoted path can't be matched against the code prefixes.
"""

from __future__ import annotations

import sys

# Paths whose change needs the suite. Same set the workflow's trigger used
# to filter on.
CODE_PREFIXES = ("src/", "tests/", "scripts/", "schemas/", ".github/workflows/")
CODE_FILES = ("pyproject.toml", "Makefile")


def needs_tests(path: str) -> bool:
    if path.startswith('"'):
        return True
    if path.startswith(CODE_PREFIXES) or path in CODE_FILES:
        return True
    return path.startswith("requirements-") and path.endswith(".txt") and "/" not in path


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
