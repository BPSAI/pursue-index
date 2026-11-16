"""Autopilot children get an allowlisted environment, never the parent's.

Every child gets process basics, the SSH agent, the non-secret PURSUE_*
settings, this package's PYTHONPATH and NO_PURSUE_DOTENV=1. Only
`pursue storage verify` also gets the storage credentials.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.tranche_autopilot import AutopilotConfig, ExitCode, run_autopilot
from pursue_index.tranche_autopilot.child_env import STORAGE_KEYS, base_env, ssh_env, storage_env
from tests.support.autopilot_fakes import SHA, FakeRunner, make_checkout, receipt

_PARENT = {
    "PATH": "/usr/bin", "HOME": "/home/op", "SSH_AUTH_SOCK": "/tmp/agent",
    "PURSUE_DATA_ROOT": "/data", "PURSUE_LOG_LEVEL": "INFO", "PURSUE_VOYAGE_API_KEY": "x",
    "ANTHROPIC_API_KEY": "x", "VOYAGE_API_KEY": "x", "GH_TOKEN": "x", "GITHUB_TOKEN": "x",
    "GIT_SSH_COMMAND": "x", "PYTHONPATH": "/evil", "LD_PRELOAD": "x",
    "R2_ACCESS_KEY_ID": "x", "R2_SECRET_ACCESS_KEY": "x", "BACKUP_R2_SECRET_ACCESS_KEY": "x",
}


def test_the_base_env_is_an_allowlist() -> None:
    env = base_env(_PARENT, "/pkg/src")
    # No SSH agent, and no PURSUE_* name that looks like a credential.
    assert set(env) == {"PATH", "HOME", "PURSUE_DATA_ROOT", "PURSUE_LOG_LEVEL",
                        "NO_PURSUE_DOTENV", "PYTHONPATH"}
    assert env["NO_PURSUE_DOTENV"] == "1" and env["PYTHONPATH"] == "/pkg/src"


def test_the_storage_env_holds_only_storage_keys() -> None:
    assert set(storage_env(_PARENT)) == {"R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                                         "BACKUP_R2_SECRET_ACCESS_KEY"}
    assert set(storage_env(_PARENT)) <= set(STORAGE_KEYS)


def test_only_storage_verify_gets_the_storage_credentials(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    (tmp_path / "root").mkdir()
    code = run_autopilot(AutopilotConfig(
        SHA, tmp_path / "result.json", repo, runner,
        base_env(_PARENT | {"PURSUE_DATA_ROOT": str(tmp_path / "root")}, "/pkg/src"),
        lambda _r: 0, storage_env=storage_env(_PARENT), ssh_env=ssh_env(_PARENT)))
    assert code == ExitCode.DONE
    for argv, env in zip(runner.calls, runner.envs, strict=True):
        if env is None:
            continue
        has_storage = "R2_SECRET_ACCESS_KEY" in env
        assert has_storage == (argv[-2:] == ["storage", "verify"]), argv
        assert ("SSH_AUTH_SOCK" in env) == ("fetch" in argv), argv
        assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env
