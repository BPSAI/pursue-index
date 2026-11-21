"""Print ``true`` when any changed path needs the Python test suite, else ``false``.

Reads one changed path per line on stdin (``git diff --name-only`` output).
Used by the ``pytest`` job in ``.github/workflows/tests.yml``, which must
report on every pull request because branch protection requires it, but
only needs to run the suite when code or tests changed.

Fails safe: empty input (no diff could be computed) prints ``true``.
"""

from __future__ import annotations

import sys

# Paths whose change needs the suite. Same set the workflow's trigger used
# to filter on.
CODE_PREFIXES = ("src/", "tests/", "scripts/", "schemas/", ".github/workflows/")
CODE_FILES = ("pyproject.toml", "Makefile")


def needs_tests(path: str) -> bool:
    if path.startswith(CODE_PREFIXES) or path in CODE_FILES:
        return True
    return path.startswith("requirements-") and path.endswith(".txt") and "/" not in path


def main() -> int:
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print("true" if not paths or any(needs_tests(p) for p in paths) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
