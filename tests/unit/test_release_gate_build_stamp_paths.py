"""The release gate runs on a change to any file the build stamp covers.

Step 4d.1 verifies data/build-stamp.json, but only on PRs the workflow's
``paths`` filter selects. If a stamped folder were missing from that list, a
hand edit there would merge without the check ever running.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_stamp  # noqa: E402


def _trigger_paths() -> list[str]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release-gate.yml").read_text())
    on = workflow.get("on") or workflow.get(True)  # PyYAML reads a bare `on:` as True
    return on["pull_request"]["paths"]


def test_release_gate_triggers_on_every_stamped_root() -> None:
    paths = _trigger_paths()
    for root in build_stamp.BUNDLE_ROOTS:
        # A file inside a folder root, or the root itself when it is a file.
        probe = root if root.endswith((".json", ".txt")) else f"{root}/any/file.json"
        assert any(fnmatch.fnmatchcase(probe, pattern) for pattern in paths), root


def test_the_stamp_and_its_verifier_trigger_the_gate() -> None:
    paths = _trigger_paths()
    assert "data/build-stamp.json" in paths and "scripts/build_stamp.py" in paths
