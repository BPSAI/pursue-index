"""Every script puts its own checkout's ``src/`` on ``sys.path`` before it
imports the package, and never builds an import path from the data root."""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

BOOTSTRAP = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "# Code is loaded from where this script lives, never from the data root\n"
    "# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.\n"
    'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n'
    "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
)
_IMPORTS_PKG = re.compile(r"^(?:from|import) pursue_index\b", re.M)
_ROOT_DERIVED_PATH = re.compile(
    r"sys\.path\.(?:insert|append)\([^)]*(?:REPO_ROOT|repo_root)", re.I
)


def _package_scripts() -> list[Path]:
    return [
        p
        for p in sorted(SCRIPTS.glob("*.py"))
        if not p.name.startswith("_")
        and "pursue_index" in p.read_text(encoding="utf-8")
    ]


def test_bootstrap_precedes_first_package_import_in_every_script() -> None:
    bad: list[str] = []
    for path in _package_scripts():
        text = path.read_text(encoding="utf-8")
        head, sep, _ = text.partition(BOOTSTRAP)
        first = _IMPORTS_PKG.search(text)
        if not sep or (first is not None and first.start() < len(head)):
            bad.append(path.name)
    assert not bad, f"missing or late sys.path bootstrap: {bad}"


def test_no_script_builds_an_import_path_from_the_data_root() -> None:
    bad = [
        p.name
        for p in sorted(SCRIPTS.glob("*.py"))
        if _ROOT_DERIVED_PATH.search(p.read_text(encoding="utf-8"))
    ]
    assert not bad, f"import path derived from repo_root(): {bad}"
