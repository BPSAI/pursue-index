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
    for name in ("wait_for_check_run.py", "check_deployed_commit.py"):
        step = _steps()[_index(name)]
        cond = step["if"]
        assert "github.event_name" in cond and "inputs.skip_build_wait" in cond
    assert any("skip_build_wait" in str(s.get("run", "")) for s in _steps())


def test_actions_stay_sha_pinned_and_no_new_third_party_action():
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert all("@" in u and len(u.split("@")[1].split()[0]) >= 40 for u in uses if not u.startswith("actions/checkout@v"))
    assert {u.split("@")[0] for u in uses} == {"actions/checkout", "actions/setup-python", "actions/github-script"}
