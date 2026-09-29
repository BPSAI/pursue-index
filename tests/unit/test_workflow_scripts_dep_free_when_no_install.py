"""Guards the bug class behind issue #162 across every workflow.

A ``.github/workflows/*.yml`` job that never runs a ``pip install`` step
executes its Python scripts in a bare interpreter — whatever
``actions/setup-python`` provides, no more. ``pursue_index/__init__.py``
unconditionally imports third-party packages (structlog,
pydantic-settings via ``pursue_index.config.settings``), so any script
run by such a job must not import ``pursue_index`` (or any submodule) at
module level, directly or transitively — that import always runs the
package ``__init__`` first, in any Python import system.

This is a static check (AST, not execution) so it covers every script in
one pass without needing per-script isolated-subprocess plumbing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_SCRIPT_RE = re.compile(r"\bscripts/([A-Za-z0-9_\-]+\.py)\b")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _run_text(step: dict) -> str:
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _iter_job_steps(workflow: dict):
    """Yield (job_name, steps) for every job in the workflow, including
    matrix/reusable-call jobs that have no ``steps`` key (skipped)."""
    for job_name, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps")
        if isinstance(steps, list):
            yield job_name, steps


def _scripts_invoked_without_prior_install(steps: list[dict]) -> set[str]:
    """Script basenames run by a step with no earlier ``pip install`` in
    the same job's step list."""
    offenders: set[str] = set()
    deps_installed = False
    for step in steps:
        text = _run_text(step)
        if "pip install" in text:
            deps_installed = True
            continue
        if not deps_installed:
            offenders.update(_SCRIPT_RE.findall(text))
    return offenders


def _has_module_level_pursue_index_import(script_path: Path) -> bool:
    tree = ast.parse(script_path.read_text(), filename=str(script_path))

    def _scan(body: list[ast.stmt]) -> bool:
        for node in body:
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "pursue_index" or alias.name.startswith("pursue_index.")
                    for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and (
                    node.module == "pursue_index" or node.module.startswith("pursue_index.")
                ):
                    return True
            elif isinstance(node, ast.If):
                # e.g. `if TYPE_CHECKING:` guards — still module-level.
                if _scan(node.body) or _scan(node.orelse):
                    return True
        return False

    return _scan(tree.body)


def _dep_free_scripts_with_pursue_index_import() -> list[str]:
    violations: list[str] = []
    for workflow_path in _workflow_files():
        workflow = yaml.safe_load(workflow_path.read_text())
        for job_name, steps in _iter_job_steps(workflow):
            for script_name in sorted(_scripts_invoked_without_prior_install(steps)):
                script_path = REPO_ROOT / "scripts" / script_name
                if not script_path.is_file():
                    continue
                if _has_module_level_pursue_index_import(script_path):
                    violations.append(
                        f"{workflow_path.name}::{job_name} runs scripts/{script_name} "
                        f"without installing dependencies first, but it imports "
                        f"pursue_index at module level"
                    )
    return violations


def test_no_dep_free_job_runs_a_script_that_imports_pursue_index() -> None:
    violations = _dep_free_scripts_with_pursue_index_import()
    assert not violations, "\n".join(violations)


def test_sweep_actually_finds_scripts_to_check() -> None:
    """Sanity check that the sweep isn't vacuously passing because the
    regex/heuristics failed to match anything."""
    checked = 0
    for workflow_path in _workflow_files():
        workflow = yaml.safe_load(workflow_path.read_text())
        for _job_name, steps in _iter_job_steps(workflow):
            for step in steps:
                checked += len(_SCRIPT_RE.findall(_run_text(step)))
    assert checked > 5
