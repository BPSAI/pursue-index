"""``.wiring-baseline.json`` allowlists only scripts something actually runs.

The wiring guard flags a module nothing imports. A standalone script is
imported by nothing by design, so it is baselined, but only while a workflow
or the Makefile runs it: a baselined script nothing runs is real dead code.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_baselined_script_is_run_by_a_workflow_or_the_makefile() -> None:
    baseline = json.loads((REPO_ROOT / ".wiring-baseline.json").read_text())
    assert baseline["schema"] == "bpsai-wiring-baseline/v1"
    runners = [p.read_text() for p in (REPO_ROOT / ".github" / "workflows").glob("*.yml")]
    runners.append((REPO_ROOT / "Makefile").read_text())
    for entry in baseline["entries"]:
        path = entry["file"]
        assert path.startswith("scripts/") and entry["kind"] == "module", entry
        assert (REPO_ROOT / path).is_file(), path
        assert any(f"python {path}" in text or f"$(PYTHON) {path}" in text
                   for text in runners), f"{path} is baselined but nothing runs it"
