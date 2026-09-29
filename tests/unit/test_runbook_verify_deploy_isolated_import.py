"""Regression test for issue #162.

``.github/workflows/post-deploy-verify.yml`` runs ``scripts/
runbook_verify_deploy.py`` in a bare ``actions/setup-python`` environment
with no dependency-install step. The script used to import
``pursue_index.release.chunked_asset`` via the package path, which runs
``pursue_index/__init__.py`` first — and that unconditionally imports
``structlog`` and ``pursue_index.config.settings``, neither available in
that job. Every run since PR #158 died with ``ModuleNotFoundError``.

This test proves the script's import path is safe in an interpreter that
cannot see any third-party package (``python -I -S``), matching the CI
job's actual environment.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "runbook_verify_deploy.py"


def test_runs_in_isolated_interpreter_with_no_third_party_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "ModuleNotFoundError" not in result.stderr
