"""Guards the bug class behind issue #162 across every workflow.

A ``.github/workflows/*.yml`` job that never runs a ``pip install`` step
executes its Python scripts in a bare interpreter — whatever
``actions/setup-python`` provides, no more. ``pursue_index/__init__.py``
unconditionally imports third-party packages (structlog,
pydantic-settings via ``pursue_index.config.settings``), so any script
run by such a job must not import ``pursue_index`` (or any submodule) at
module level — directly, or transitively through a local sibling module
under ``scripts/`` it imports (e.g. ``from _wayback_helpers import
...``) — nor any *other* third-party top-level module, since these jobs
install nothing at all.

This is a static check (AST, not execution) so it covers every script,
and every local module it pulls in, in one pass without needing
per-script isolated-subprocess plumbing. Loading a module by file path
(``importlib.util.spec_from_file_location`` — the #162 fix itself) is
deliberately invisible to this scan: it's a function call, not an
``import``/``from`` statement, and it's exactly how a script is supposed
to reach stdlib-only sibling code without tripping this rule.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
SCRIPTS_DIR = REPO_ROOT / "scripts"

_SCRIPT_RE = re.compile(r"\bscripts/([A-Za-z0-9_\-]+\.py)\b")
_STDLIB = sys.stdlib_module_names


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


def _module_level_import_names(script_path: Path) -> list[str]:
    """Dotted names of every module-level ``import``/``from`` statement,
    following into ``if`` blocks (e.g. ``TYPE_CHECKING`` guards) — still
    module scope, just conditional. Does NOT descend into functions or
    classes: an import needed lazily to dodge a missing dependency isn't
    executed just by loading the module, so it can't trip this rule."""
    tree = ast.parse(script_path.read_text(), filename=str(script_path))
    names: list[str] = []

    def _scan(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module)
            elif isinstance(node, ast.If):
                _scan(node.body)
                _scan(node.orelse)

    _scan(tree.body)
    return names


def _import_closure_violation(script_path: Path, *, _visited: set[Path] | None = None) -> str | None:
    """The first disallowed import reached from ``script_path``, or
    ``None`` if the whole closure is clean.

    "Disallowed" is ``pursue_index`` (any submodule) or any other
    top-level module that is neither stdlib nor a local sibling file
    under the same directory as ``script_path`` (covers both "resolvable
    under scripts/" and a script's own ``sys.path.insert`` onto
    ``scripts/`` or ``src/`` — a script always ends up on sys.path
    itself when run directly, and ``pursue_index`` is matched by name
    regardless of how sys.path got set up, since that's exactly how the
    real ModuleNotFoundError happens). A local sibling is followed
    transitively; ``_visited`` guards against import cycles between
    helpers so that traversal always terminates.
    """
    if _visited is None:
        _visited = set()
    resolved = script_path.resolve()
    if resolved in _visited:
        return None
    _visited.add(resolved)

    for name in _module_level_import_names(script_path):
        if name == "pursue_index" or name.startswith("pursue_index."):
            return name
        top = name.split(".", 1)[0]
        if top in _STDLIB:
            continue
        sibling = script_path.parent / f"{top}.py"
        if sibling.is_file():
            violation = _import_closure_violation(sibling, _visited=_visited)
            if violation is not None:
                return violation
            continue
        # Not stdlib, not pursue_index, not a local sibling module: some
        # other third-party top-level import — the job installs nothing,
        # so this ModuleNotFoundErrors exactly like pursue_index would.
        return name
    return None


def _dep_free_scripts_with_import_violations() -> list[str]:
    violations: list[str] = []
    for workflow_path in _workflow_files():
        workflow = yaml.safe_load(workflow_path.read_text())
        for job_name, steps in _iter_job_steps(workflow):
            for script_name in sorted(_scripts_invoked_without_prior_install(steps)):
                script_path = SCRIPTS_DIR / script_name
                if not script_path.is_file():
                    continue
                violation = _import_closure_violation(script_path)
                if violation is not None:
                    violations.append(
                        f"{workflow_path.name}::{job_name} runs scripts/{script_name} "
                        f"without installing dependencies first, but its import closure "
                        f"reaches {violation!r}"
                    )
    return violations


def test_no_dep_free_job_runs_a_script_that_imports_pursue_index() -> None:
    violations = _dep_free_scripts_with_import_violations()
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


# ---------------------------------------------------------------------
# Fixture tests for `_import_closure_violation` itself (Codex PR #163
# round-2 P2): each proves one shape of the traversal actually works,
# not just that today's real scripts happen to pass.
# ---------------------------------------------------------------------


def test_closure_direct_violation(tmp_path: Path) -> None:
    """A script that imports pursue_index itself is caught directly."""
    entry = tmp_path / "entry.py"
    entry.write_text("import pursue_index.release.chunked_asset\n")
    assert _import_closure_violation(entry) == "pursue_index.release.chunked_asset"


def test_closure_transitive_violation_via_helper(tmp_path: Path) -> None:
    """entry.py imports nothing disallowed itself, but pulls in a local
    sibling helper that does — the two-hop case the direct-only check
    (the pre-#163-round-2 version of this scan) could not see."""
    (tmp_path / "_helper.py").write_text("import pursue_index\n")
    entry = tmp_path / "entry.py"
    entry.write_text("from _helper import thing\n")
    assert _import_closure_violation(entry) == "pursue_index"


def test_closure_cycle_between_helpers_terminates_clean(tmp_path: Path) -> None:
    """a.py <-> b.py import each other; neither reaches anything
    disallowed. Must terminate (not hang) and report no violation."""
    (tmp_path / "a.py").write_text("import b\nimport os\n")
    (tmp_path / "b.py").write_text("import a\nimport sys\n")
    assert _import_closure_violation(tmp_path / "a.py") is None


def test_closure_importlib_by_path_pattern_not_flagged(tmp_path: Path) -> None:
    """The #162 fix's own pattern — loading a sibling module by file path
    via importlib.util instead of a package import — must NOT be treated
    as reaching pursue_index. It's a function call, not an import
    statement, and it's exactly how a script legitimately dodges a
    missing-dependency package __init__."""
    entry = tmp_path / "entry.py"
    entry.write_text(
        "import importlib.util\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('chunked_asset', "
        "Path(__file__).parent / 'chunked_asset.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
    )
    assert _import_closure_violation(entry) is None
