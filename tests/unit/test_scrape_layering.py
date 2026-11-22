"""The scrape layer sits below tranche_ready: it must not import from it, and
the shared text-neutralizing helper lives in a low-level module both can use."""

from __future__ import annotations

import ast
from pathlib import Path

import pursue_index.scrape as scrape_pkg


def _imported_modules(path: Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def test_scrape_imports_nothing_from_tranche_ready() -> None:
    offenders = []
    for path in Path(scrape_pkg.__file__).parent.rglob("*.py"):
        bad = {m for m in _imported_modules(path) if "tranche_ready" in m.split(".")}
        if bad:
            offenders.append((path.name, sorted(bad)))
    assert offenders == []


def test_neutralize_lives_in_text_safety_and_tranche_ready_reexports_it() -> None:
    from pursue_index.text_safety import neutralize
    from pursue_index.tranche_ready.refusal import neutralize as reexported

    assert reexported is neutralize
