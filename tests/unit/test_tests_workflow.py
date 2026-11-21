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


def _classify_raw(data: str) -> str:
    out = subprocess.run(
        [sys.executable, str(CLASSIFIER)], input=data,
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_nul_separated_input_with_a_non_ascii_code_path_runs_the_suite() -> None:
    """`git diff -z` output: NUL-separated, paths unquoted even when non-ASCII."""
    assert _classify_raw("data/manifests/latest.json\0src/pursue_index/café.py\0") == "true"


def test_nul_separated_data_only_input_does_not() -> None:
    assert _classify_raw("data/manifests/latest.json\0web/src/data/café.json\0") == "false"


def test_a_git_quoted_path_is_treated_as_needing_tests() -> None:
    """Backstop: a C-quoted path (git's default for non-ASCII) never skips."""
    assert _classify_raw('"src/\\303\\251.py"\n') == "true"
    assert _classify_raw('data/x.json\n"web/\\303\\251.json"\n') == "true"


def test_the_decision_step_asks_git_for_unquoted_nul_separated_paths() -> None:
    step = next(s for s in _workflow()["jobs"]["pytest"]["steps"] if s.get("id") == "changes")
    assert "core.quotePath=false" in step["run"]
    assert "--name-only -z" in step["run"] or "--no-renames --name-only -z" in step["run"]


def test_undecodable_bytes_do_not_crash_the_classifier() -> None:
    out = subprocess.run(
        [sys.executable, str(CLASSIFIER)], input=b"data/x.json\0src/\xff\xfe.py\0",
        capture_output=True, check=True,
    )
    assert out.stdout.decode().strip() == "true"


def test_anything_but_an_explicit_false_runs_the_suite() -> None:
    """A classifier crash leaves `code` empty: that must still run the suite."""
    step = next(s for s in _workflow()["jobs"]["pytest"]["steps"] if s.get("id") == "changes")
    assert '[ "$code" = "false" ] || code=true' in step["run"]


def _decision_diff_command() -> str:
    step = next(s for s in _workflow()["jobs"]["pytest"]["steps"] if s.get("id") == "changes")
    line = next(ln for ln in step["run"].splitlines() if "git " in ln and " diff " in ln)
    return line[line.index("git "):line.index('"$BASE_SHA...$HEAD_SHA"')].strip()


def test_the_decision_step_disables_rename_detection() -> None:
    assert "--no-renames" in _decision_diff_command()


def test_moving_a_file_out_of_src_runs_the_suite(tmp_path: Path) -> None:
    """With rename detection a move lists only the NEW path; both must appear."""
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
             "-c", "commit.gpgsign=false", *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    git("init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("print('x')\n" * 20)
    git("add", "-A"); git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    git("mv", "src/x.py", "docs/x.py"); git("commit", "-q", "-m", "move")
    head = git("rev-parse", "HEAD")

    cmd = _decision_diff_command().split()[1:]  # drop the leading "git"
    diff = subprocess.run(
        ["git", "-C", str(tmp_path), *cmd, f"{base}...{head}"],
        capture_output=True, check=True,
    ).stdout
    out = subprocess.run([sys.executable, str(CLASSIFIER)], input=diff,
                         capture_output=True, check=True)
    assert out.stdout.decode().strip() == "true"
