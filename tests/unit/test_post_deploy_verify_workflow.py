"""Shape of ``.github/workflows/post-deploy-verify.yml``: verify THIS commit's deploy."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "post-deploy-verify.yml"


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict]:
    return _wf()["jobs"]["verify"]["steps"]


def _index(needle: str) -> int:
    for i, s in enumerate(_steps()):
        if needle in str(s.get("run", "")):
            return i
    raise AssertionError(f"no step runs {needle}")


def test_checks_read_is_granted():
    assert _wf()["permissions"]["checks"] == "read"


def test_wait_step_precedes_stamp_step_precedes_url_verify():
    assert _index("wait_for_check_run.py") < _index("check_deployed_commit.py") < _index("runbook_verify_deploy.py")


def test_wait_step_uses_github_sha_and_env_token():
    step = _steps()[_index("wait_for_check_run.py")]
    assert "github.sha" in step["run"]
    assert "secrets.GITHUB_TOKEN" in step["env"]["GITHUB_TOKEN"]
    assert "secrets." not in step["run"]


def test_stamp_step_uses_github_sha():
    assert "github.sha" in _steps()[_index("check_deployed_commit.py")]["run"]


def test_no_fixed_sleep():
    assert "sleep" not in WORKFLOW.read_text().replace("sleep-", "")


def test_skip_build_wait_input_defaults_false_and_push_never_skips():
    inputs = _wf()[True]["workflow_dispatch"]["inputs"]
    assert str(inputs["skip_build_wait"]["default"]).lower() == "false"
    cond = _steps()[_index("wait_for_check_run.py")]["if"]
    assert "github.event_name" in cond and "inputs.skip_build_wait" in cond
    assert any("skip_build_wait" in str(s.get("run", "")) for s in _steps())


def test_actions_stay_sha_pinned_and_no_new_third_party_action():
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert all("@" in u and len(u.split("@")[1].split()[0]) >= 40 for u in uses if not u.startswith("actions/checkout@v"))
    assert {u.split("@")[0] for u in uses} == {"actions/checkout", "actions/setup-python", "actions/github-script"}


def _text() -> str:
    return WORKFLOW.read_text()


def test_actions_read_is_granted():
    assert _wf()["permissions"]["actions"] == "read"


def test_no_inputs_expression_inside_any_run_script():
    for s in _steps():
        assert "${{ inputs." not in str(s.get("run", "")), s.get("name")
        assert "${{ github.event.inputs" not in str(s.get("run", "")), s.get("name")


def test_base_url_reaches_scripts_via_env_and_is_validated_first():
    wf = _wf()
    env_blob = str(wf["env"]) + "".join(str(s.get("env", "")) for s in _steps())
    assert "inputs.base_url" in env_blob
    assert _index("validate_base_url.py") < _index("wait_for_check_run.py")


def test_check_name_defined_once_in_workflow_env():
    assert "WORKERS_BUILD_CHECK_NAME" in _wf()["env"]
    assert _text().count("Workers Builds: pursue-index") <= 2  # env value + header comment
    assert "--name" not in _text()


def test_later_steps_skip_when_superseded():
    for needle in ("check_deployed_commit.py", "runbook_verify_deploy.py"):
        assert "superseded" in _steps()[_index(needle)]["if"]


def test_npm_test_includes_deploy_stamp():
    import json

    scripts = json.loads((WORKFLOW.parents[2] / "web" / "package.json").read_text())["scripts"]
    assert "test:deploy-stamp" in scripts
    assert "npm run test:deploy-stamp" in scripts["test"]


def test_skip_build_wait_still_runs_the_deployed_commit_check_and_warns():
    cond = _steps()[_index("check_deployed_commit.py")].get("if", "")
    assert "skip_build_wait" not in cond
    warn = [s for s in _steps() if "::warning" in str(s.get("run", ""))]
    assert warn and "SKIP_BUILD_WAIT" in str(warn[0]["env"])


def test_app_id_defined_once_in_workflow_env():
    assert _wf()["env"]["WORKERS_BUILD_APP_ID"] == "85455"


FAILURE_ISSUE_RESERVE_SECS = 120  # room left in the job for the failure-issue step


def _flag(step_name_needle: str, flag: str) -> int:
    import re

    run = str(_steps()[_index(step_name_needle)]["run"])
    return int(re.search(re.escape(flag) + r"\s+(\d+)", run).group(1))


def test_max_wait_cap_fits_inside_the_job_timeout():
    wf = _wf()
    budget = wf["jobs"]["verify"]["timeout-minutes"] * 60
    cap = int(wf["env"]["MAX_WAIT_SECS_CAP"])
    build_wait = _flag("wait_for_check_run.py", "--timeout-secs")
    stamp_wait = _flag("check_deployed_commit.py", "--timeout-secs")
    assert cap + build_wait + stamp_wait + FAILURE_ISSUE_RESERVE_SECS <= budget
    assert int(wf["env"]["MAX_WAIT_SECS"].split("'")[-2]) <= cap  # the default fits too


def test_validate_step_receives_the_cap_through_the_workflow_env():
    # validate_base_url.py reads MAX_WAIT_SECS and MAX_WAIT_SECS_CAP from the job env
    assert "MAX_WAIT_SECS" in _wf()["env"] and "MAX_WAIT_SECS_CAP" in _wf()["env"]
