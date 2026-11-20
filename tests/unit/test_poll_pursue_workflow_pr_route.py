"""The poll and verify workflows reach main only through a reviewed PR.

Structure pins on ``.github/workflows/poll-pursue.yml`` and
``verify-assets-daily.yml``:

* no step pushes to ``main``: every ``git push`` names an explicit
  ``refs/heads/<branch>`` whose branch resolves (through step env, job
  outputs and the step that names it) to ``poll/...`` or ``verify/...``;
* the fetched CSV bytes are saved as a workflow artifact before any step
  commits or pushes, gated only on the poll and the byte verification;
* a promote job, after ``poll`` and ``snapshot``, opens one PR from the
  ``poll/`` branch into ``main``, and opens none while one is already open.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
_ALLOWED = ("poll/", "verify/")
_PUSH = re.compile(r"\bgit\s+push\b[^\n]*")
_DEST = re.compile(r'^git\s+push\s+origin\s+"[^"\s:]+(?:\([^)]*\))?[^"\s:]*:refs/heads/'
                   r'\$\{(\w+)\}"\s*$')
_EXPR = re.compile(r"^\$\{\{\s*([\w.]+)\s*\}\}$")


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _command_lines(run: str) -> list[str]:
    return [ln.strip() for ln in run.splitlines() if not ln.strip().startswith("#")]


def _resolve(value: str, workflow: dict, job: str) -> str:
    """A branch value as a literal prefix: follow ``needs.<job>.outputs.<x>``
    and ``steps.<id>.outputs.name`` to the step that writes ``name=...``."""
    match = _EXPR.match(value.strip())
    if not match:
        return value
    parts = match.group(1).split(".")
    if parts[0] == "needs":
        out = workflow["jobs"][parts[1]]["outputs"][parts[3]]
        return _resolve(str(out), workflow, parts[1])
    if parts[0] == "steps" and parts[2:] == ["outputs", "name"]:
        [step] = [s for s in workflow["jobs"][job]["steps"] if s.get("id") == parts[1]]
        named = re.search(r'^name="([^"$]*)', str(step["run"]), re.M)
        assert named and 'echo "name=${name}"' in step["run"], f"unresolvable {value}"
        return named.group(1)
    raise AssertionError(f"cannot resolve branch expression {value!r}")


def _push_targets(workflow: dict) -> list[tuple[str, str]]:
    """``(push line, resolved branch)`` for every push in every step."""
    out = []
    for job_id, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            for line in _command_lines(str(step.get("run", ""))):
                for push in _PUSH.findall(line):
                    dest = _DEST.match(push)
                    assert dest, f"push without an explicit refs/heads/ target: {push!r}"
                    var = dest.group(1)
                    value = (step.get("env") or {}).get(var)
                    assert value, f"{push!r}: ${var} is not set in the step's env"
                    out.append((push, _resolve(str(value), workflow, job_id)))
    return out


@pytest.mark.parametrize("name", ["poll-pursue.yml", "verify-assets-daily.yml"])
def test_no_step_pushes_to_main(name: str) -> None:
    targets = _push_targets(_load(name))
    assert targets, "expected the workflow to push its bot branch"
    for push, branch in targets:
        assert "main" not in push.split(":")[-1], push
        assert branch.startswith(_ALLOWED), f"{push!r} targets {branch!r}"


def _poll_steps() -> list[dict]:
    return _load("poll-pursue.yml")["jobs"]["poll"]["steps"]


def _index(steps: list[dict], name_part: str) -> int:
    [i] = [i for i, s in enumerate(steps) if name_part in str(s.get("name", ""))]
    return i


def test_csv_artifact_is_saved_before_any_commit_or_push() -> None:
    steps = _poll_steps()
    save = _index(steps, "Save fetched CSV bytes as a workflow artifact")
    writers = [i for i, s in enumerate(steps)
               if re.search(r"\bgit\s+(?:-C\s+\S+\s+)?(commit|push)\b", str(s.get("run", "")))]
    assert writers and all(save < i for i in writers)
    verify = _index(steps, "Verify fetched CSV bytes")
    run_poll = next(i for i, s in enumerate(steps) if s.get("id") == "poll")
    assert run_poll < verify < save


def test_csv_artifact_step_depends_only_on_the_poll_and_verify_steps() -> None:
    steps = _poll_steps()
    save = steps[_index(steps, "Save fetched CSV bytes as a workflow artifact")]
    verify = steps[_index(steps, "Verify fetched CSV bytes")]
    assert "upload-artifact" in str(save.get("uses"))
    refs = set(re.findall(r"steps\.(\w+)\.", str(save.get("if", "")) + str(save.get("with"))))
    assert refs and refs <= {"poll", verify["id"]}
    assert f"steps.{verify['id']}.outcome == 'success'" in str(save["if"])
    assert set(re.findall(r"steps\.(\w+)\.", str(verify.get("if", "")))) <= {"poll"}


def _promote() -> tuple[dict, str, dict]:
    workflow = _load("poll-pursue.yml")
    jobs = [(j, job) for j, job in workflow["jobs"].items()
            if any("gh pr create" in str(s.get("run", "")) and "POLL_BRANCH" in str(s.get("run"))
                   for s in job.get("steps", []))]
    assert len(jobs) == 1, "exactly one job opens the poll/<sha12> promote PR"
    job_id, job = jobs[0]
    [step] = [s for s in job["steps"] if "gh pr create" in str(s.get("run", ""))]
    return workflow, job_id, step | {"_job": job}


def test_promote_job_runs_after_poll_and_snapshot() -> None:
    _, _, step = _promote()
    needs = step["_job"]["needs"]
    assert {"poll", "snapshot"} <= set([needs] if isinstance(needs, str) else needs)


def test_promote_pr_goes_from_a_poll_branch_into_main() -> None:
    workflow, job_id, step = _promote()
    run = str(step["run"])
    start = run.index("gh pr create")
    create = run[start:run.index("\n", run.index("--body-file", start))]
    assert "--base main" in create
    head = re.search(r'--head\s+"\$(\w+)"', create)
    assert head, "the promote PR must name its head branch"
    assert _resolve(str(step["env"][head.group(1)]), workflow, job_id).startswith("poll/")


def test_promote_dedupes_on_an_existing_open_pr() -> None:
    _, _, step = _promote()
    run = str(step["run"])
    lookup = run.index("gh pr list")
    create = run.index("gh pr create")
    listing = run[lookup:run.index("\n", lookup)]
    assert '--head "$POLL_BRANCH"' in listing and "--base main" in listing
    assert "--state open" in listing
    guard = run[run.index("\n", lookup):create]
    assert re.search(r'if \[ -n "\$open" \]; then[^\n]*\n[^\n]*\n\s*exit 0\n\s*fi', guard), \
        "an open PR must end the step before gh pr create"
