"""AGENCY_ORDER lives in Python (atlas build guard) and TypeScript (legend).

Each side has its own test against its own copy; this one pins the two
copies to each other so a one-sided edit fails here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TS_FILE = REPO_ROOT / "web" / "src" / "components" / "atlas-helpers.ts"
SCRIPT = REPO_ROOT / "scripts" / "build_atlas_layout.py"


def _load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_atlas_layout", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ts_agency_order() -> list[str]:
    src = TS_FILE.read_text(encoding="utf-8")
    block = re.search(r"AGENCY_ORDER\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert block, "AGENCY_ORDER literal not found in atlas-helpers.ts"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_python_and_typescript_agency_order_match() -> None:
    assert list(_load_script().AGENCY_ORDER) == _ts_agency_order()
