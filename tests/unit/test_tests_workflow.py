"""The required ``pytest`` check reports on every pull request.

Branch protection requires a check named ``pytest``. With a ``paths`` filter
on the trigger, a PR touching only data never started the workflow, so the
required check never reported and the PR stayed blocked. The workflow now
runs on every PR, and the ``pytest`` job decides inside itself whether any
code or test path changed: if none did it passes in seconds, otherwise it
runs the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
CLASSIFIER = ROOT / "scripts" / "ci_code_paths_changed.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(data: dict) -> dict:
    # YAML 1.1 reads a bare `on:` key as boolean True.
    return data.get("on", data.get(True))


def _classify(paths: list[str]) -> str:
    out = subprocess.run(
        [sys.executable, str(CLASSIFIER)],
        input="\n".join(paths) + ("\n" if paths else ""),
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_pull_request_trigger_has_no_path_filter() -> None:
    pr = _triggers(_workflow())["pull_request"] or {}
    assert "paths" not in pr and "paths-ignore" not in pr


def test_the_required_check_keeps_its_name() -> None:
    jobs = _workflow()["jobs"]
    assert "pytest" in jobs
    assert "name" not in jobs["pytest"] or jobs["pytest"]["name"] == "pytest"
    # A job-level `if` would make the check report as skipped, not passed.
    assert "if" not in jobs["pytest"]


def test_every_step_after_the_decision_is_gated_on_it() -> None:
    steps = _workflow()["jobs"]["pytest"]["steps"]
    ids = [s.get("id") for s in steps]
    assert "changes" in ids
    after = steps[ids.index("changes") + 1:]
    gated = [s for s in after if "steps.changes.outputs.code == 'true'" in str(s.get("if", ""))]
    notice = [s for s in after if "steps.changes.outputs.code != 'true'" in str(s.get("if", ""))]
    assert len(notice) == 1, "one visible step says the suite was skipped"
    assert len(gated) + len(notice) == len(after), "every later step depends on the decision"
    assert any("pytest" in str(s.get("run", "")) for s in gated)


def test_the_decision_step_reads_shas_from_env_not_inline() -> None:
    step = next(s for s in _workflow()["jobs"]["pytest"]["steps"] if s.get("id") == "changes")
    assert "${{" not in step["run"], "expressions go through env, never into the script"
    assert "ci_code_paths_changed.py" in step["run"]


@pytest.mark.parametrize("path", [
    "src/pursue_index/cli.py", "tests/unit/test_x.py", "scripts/poll_pursue.py",
    "schemas/card.json", "pyproject.toml", "requirements-dev.txt", "Makefile",
    ".github/workflows/tests.yml",
])
def test_code_and_test_paths_count_as_changed(path: str) -> None:
    assert _classify([path]) == "true"


@pytest.mark.parametrize("paths", [
    ["data/manifests/latest.json"],
    ["web/public/data/clean-qc-bundle.json", "web/src/data/manifest.json"],
    ["README.md", "docs/notes.md"],
])
def test_data_only_changes_do_not(paths: list[str]) -> None:
    assert _classify(paths) == "false"


def test_a_mixed_change_runs_the_suite() -> None:
    assert _classify(["data/manifests/latest.json", "src/pursue_index/x.py"]) == "true"


def test_an_empty_or_unknown_diff_fails_safe_to_running() -> None:
    """No diff available (e.g. the base could not be resolved) means run."""
    assert _classify([]) == "true"
