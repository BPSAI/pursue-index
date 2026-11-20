"""The poll and verify workflows reach main only through a reviewed PR.

Structure pins on ``.github/workflows/poll-pursue.yml`` and
``verify-assets-daily.yml``:

* no step pushes to ``main``: every line that runs a push (``git push``,
  ``git -C <dir> push``, ...) must have the one accepted form, naming an
  explicit ``refs/heads/${VAR}`` whose branch resolves (through step env, job
  outputs and the step that names it) to ``poll/...`` or ``verify/...`` --
  any other form, or an expression the resolver does not know, fails;
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
_FORBIDDEN = {"main", "master"}
# A line that names both `git` and `push` as words is treated as a push and
# must parse into the one accepted form below -- anything else fails, so a
# new spelling (`git -C dir push`, `|| git push`, a bare push) can't slip by.
_PUSH_WORDS = re.compile(r"\bgit\b.*\bpush\b")
_C_OPT = r"""\s+-C\s+(?:"[^"]*"|'[^']*'|[^\s"']+)"""
_DEST = re.compile(rf'^git(?:{_C_OPT})*\s+push\s+origin\s+"[^"\s:]+(?:\([^)]*\))?[^"\s:]*'
                   r':refs/heads/\$\{(\w+)\}"\s*$')
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
                if not _PUSH_WORDS.search(line):
                    continue
                dest = _DEST.match(line)
                assert dest, f"push not in the accepted refs/heads/${{VAR}} form: {line!r}"
                var = dest.group(1)
                value = (step.get("env") or {}).get(var)
                assert value, f"{line!r}: ${var} is not set in the step's env"
                out.append((line, _resolve(str(value), workflow, job_id)))
    return out


def _check_pushes(workflow: dict) -> list[tuple[str, str]]:
    """Every push resolves to a ``poll/`` or ``verify/`` branch, never main."""
    targets = _push_targets(workflow)
    for push, branch in targets:
        assert branch not in _FORBIDDEN, f"{push!r} targets {branch!r}"
        assert branch.startswith(_ALLOWED), f"{push!r} targets {branch!r}"
    return targets


@pytest.mark.parametrize("name", ["poll-pursue.yml", "verify-assets-daily.yml"])
def test_no_step_pushes_to_main(name: str) -> None:
    assert _check_pushes(_load(name)), "expected the workflow to push its bot branch"


def _one_step(run: str, env: dict | None = None) -> dict:
    return {"jobs": {"j": {"steps": [{"run": run, "env": env or {}}]}}}


def test_push_guard_accepts_repeated_c_options() -> None:
    run = 'git -C "$wt" -C sub push origin "$(git -C "$wt" rev-parse HEAD):refs/heads/${B}"'
    assert _check_pushes(_one_step(run, {"B": "poll/x"})) == [(run, "poll/x")]


@pytest.mark.parametrize("run", [
    'git -C "$wt" push origin HEAD:refs/heads/main',
    "git -C /tmp/x push origin HEAD:main",
    "git push",
    'if git push origin "HEAD:refs/heads/${B}"; then :; fi',
    'git push origin "HEAD:refs/heads/main"',
])
def test_push_guard_fails_closed_on_any_other_push_form(run: str) -> None:
    with pytest.raises(AssertionError, match="accepted refs/heads"):
        _check_pushes(_one_step(run, {"B": "poll/x"}))


_PUSH_VAR = 'git -C "$wt" push origin "HEAD:refs/heads/${B}"'


@pytest.mark.parametrize("branch", ["main", "master", "release/x", "${{ github.ref_name }}",
                                    "${{ inputs.branch }}", "${{ env.BRANCH }}"])
def test_push_guard_rejects_main_and_unresolvable_branches(branch: str) -> None:
    with pytest.raises(AssertionError, match=r"targets|cannot resolve"):
        _check_pushes(_one_step(_PUSH_VAR, {"B": branch}))


def test_push_guard_rejects_a_branch_variable_missing_from_the_step_env() -> None:
    with pytest.raises(AssertionError, match=r"not set in the step's env"):
        _check_pushes(_one_step(_PUSH_VAR))


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
