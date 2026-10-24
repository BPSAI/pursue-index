"""Guard: no module under ``src/`` or ``scripts/`` derives a repo root by
counting ``.parent`` hops off its own ``__file__``.

That pattern answers with the INSTALLING checkout's location rather than the
one the process is actually running in (see ``pursue_index.paths``), which is
exactly the Release-7 bug this task fixes. Every such constant must route
through ``pursue_index.paths.repo_root()`` instead -- this test fails the
next time someone reintroduces the pattern rather than importing the
resolver.

A single ``.parent`` (no chaining, no ``.parents[...]``) is NOT flagged: that
is "this file's own directory" (locating a sibling script or asset), a
different and legitimate use that has nothing to do with repo roots.

Five scripts are allowlisted for a second reason, unrelated to the
resolver: ``check_cf_managed_bots_drift.py``, ``indexnow_ping.py``,
``runbook_verify_deploy.py``, ``wayback_save.py`` and ``registry_root.py``
(the last via ``verify_registry_root.py``'s ``from registry_root import
...``) are invoked by GitHub Actions jobs that never run ``pip install``
(see ``test_workflow_scripts_dep_free_when_no_install.py`` / issue #162) —
importing ``pursue_index.paths`` would pull in ``pursue_index/__init__.py``'s
third-party deps (structlog, pydantic-settings) and break them in that bare
interpreter. They keep the plain ``__file__``-counting form on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_DIRS = ("src", "scripts")

_SCRIPTS = REPO_ROOT / "scripts"

# The resolver itself is the one place permitted to walk up from its own
# location -- it IS the implementation of "derive a repo root from __file__".
# The rest are the dependency-free workflow scripts described above.
_ALLOWLIST = {
    REPO_ROOT / "src" / "pursue_index" / "paths.py",
    _SCRIPTS / "check_cf_managed_bots_drift.py",
    _SCRIPTS / "indexnow_ping.py",
    _SCRIPTS / "runbook_verify_deploy.py",
    _SCRIPTS / "wayback_save.py",
    _SCRIPTS / "registry_root.py",
}

# Two or more ``.parent`` hops, or any ``.parents[...]`` indexing, off
# ``Path(__file__)`` -- the shape every existing ``_REPO_ROOT`` constant used.
_MULTI_HOP = re.compile(r"Path\(__file__\)(?:\.resolve\(\))?(?:\.parent){2,}")
_INDEXED = re.compile(r"Path\(__file__\)(?:\.resolve\(\))?\.parents\[")


def _candidate_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SCANNED_DIRS:
        base = REPO_ROOT / rel
        if base.is_dir():
            files.extend(
                p for p in base.rglob("*.py") if "__pycache__" not in p.parts
            )
    return sorted(files)


def test_no_module_derives_repo_root_from_file_without_the_resolver() -> None:
    violations: list[str] = []
    for path in _candidate_files():
        if path in _ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _MULTI_HOP.search(line) or _INDEXED.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, (
        "Use pursue_index.paths.repo_root() instead of deriving a repo root "
        "from __file__ (see src/pursue_index/paths.py):\n  "
        + "\n  ".join(violations)
    )
