"""Print ``true`` if any changed path means the web-audit job must run.

Reads changed paths on stdin: NUL-separated (``git -c core.quotePath=false
diff --name-only -z``, the form the workflow uses) or one per line. Used by
``.github/workflows/web-audit.yml``, which must report on every pull request
because branch protection requires it (a ``paths:`` filter would leave the
check unreported and the PR blocked), but only needs to run npm audit when
the web app, the Worker, the gate or the Node pin changed.

Fails safe: empty input (no diff could be computed) prints ``true``, and so
does any C-quoted path. Anything on the audited list prints ``true``.

The workflow runs the BASE branch's copy of this file, so a pull request
cannot edit it to skip its own audit.
"""

from __future__ import annotations

import re
import sys

AUDITED_PREFIXES = ("web/", "worker/")
AUDITED_FILES = {
    "scripts/web_audit_gate.py",
    "scripts/web_audit_paths_changed.py",
    ".github/workflows/web-audit.yml",
    ".node-version",
    ".npmrc",
}


# The gate loads its helper modules from beside itself, so an edit to any of
# them changes the gate's decision. The rule here is deliberately broad: ANY
# scripts/_web_audit_*.py counts, whatever its name. The workflow's base-copy
# loop is narrower ([a-z0-9_]+); a test keeps this set a superset of that one,
# so a helper the workflow does not copy is still audited, never skipped.
HELPER_RE = re.compile(r"scripts/_web_audit_[^/]*\.py")


def is_helper(path: str) -> bool:
    return HELPER_RE.fullmatch(path) is not None


def needs_audit(path: str) -> bool:
    if path.startswith('"'):
        return True
    if is_helper(path):
        return True
    return path.startswith(AUDITED_PREFIXES) or path in AUDITED_FILES


def main() -> int:
    # Raw bytes, decoded leniently: an undecodable name must never crash this.
    data = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
    parts = data.split("\0") if "\0" in data else data.splitlines()
    paths = [p.strip() for p in parts if p.strip()]
    print("true" if not paths or any(needs_audit(p) for p in paths) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
