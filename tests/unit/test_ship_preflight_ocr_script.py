"""``scripts/ship_preflight_ocr.py`` -- the checked-in OCR preflight the
ship-tranche runbook runs instead of inline ``python -c``."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ship_preflight_ocr  # type: ignore[import-not-found] # noqa: E402


def test_preflight_passes_with_the_operated_config_and_a_key() -> None:
    assert ship_preflight_ocr.main({"ANTHROPIC_API_KEY": "present"}) == 0


def test_preflight_refuses_without_a_key() -> None:
    assert ship_preflight_ocr.main({}) == 1


def test_runbook_runs_the_script_not_inline_python() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "ship-tranche.md").read_text()
    assert "python scripts/ship_preflight_ocr.py" in text
    assert "python -c" not in text
    assert "Bash(git:*)" not in text
    # A tracked doc grants nothing; the operator-local command carries its own tool grants.
    assert "allowed-tools" not in text
