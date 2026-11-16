"""Autopilot children get an allowlisted environment, never the parent's.

Every child gets process basics, the SSH agent, the non-secret PURSUE_*
settings, this package's PYTHONPATH and NO_PURSUE_DOTENV=1. Only
`pursue storage verify` also gets the storage credentials.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pursue_index.tranche_autopilot import AutopilotConfig, ExitCode, run_autopilot
from pursue_index.tranche_autopilot.child_env import (
    PURSUE_ALLOWED,
    PURSUE_EXCLUDED,
    STORAGE_KEYS,
    base_env,
    storage_env,
)
from tests.support.autopilot_fakes import SHA, FakeRunner, make_checkout, receipt

_PARENT = {
    "PATH": "/usr/bin", "HOME": "/home/op", "SSH_AUTH_SOCK": "/tmp/agent",
    "PURSUE_DATA_ROOT": "/data", "PURSUE_LOG_LEVEL": "INFO", "PURSUE_CF_API_TOKEN": "x",
    "PURSUE_DB_URL": "postgres://u:p@h/db", "PURSUE_SOMETHING_NEW": "x",
    "ANTHROPIC_API_KEY": "x", "VOYAGE_API_KEY": "x", "GH_TOKEN": "x", "GITHUB_TOKEN": "x",
    "GIT_SSH_COMMAND": "x", "PYTHONPATH": "/evil", "LD_PRELOAD": "x",
    "R2_ACCESS_KEY_ID": "x", "R2_SECRET_ACCESS_KEY": "x", "BACKUP_R2_SECRET_ACCESS_KEY": "x",
}


def test_the_base_env_is_an_allowlist() -> None:
    env = base_env(_PARENT, "/pkg/src")
    # No SSH agent, no credential, and no PURSUE_* name off the allowlist.
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
        lambda _r: 0, storage_env=storage_env(_PARENT)))
    assert code == ExitCode.DONE
    for argv, env in zip(runner.calls, runner.envs, strict=True):
        if env is None:
            continue
        has_storage = "R2_SECRET_ACCESS_KEY" in env
        assert has_storage == (argv[-2:] == ["storage", "verify"]), argv
        assert "SSH_AUTH_SOCK" not in env, argv
        assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env


def test_every_pursue_name_in_the_code_is_allowed_or_excluded() -> None:
    root = Path(__file__).resolve().parents[2]
    found = subprocess.run(
        ["git", "-C", str(root), "grep", "-ohE", r"PURSUE_[A-Z0-9_]+", "--",
         "src", "scripts", "Makefile", "web/scripts", "web/src"],
        capture_output=True, text=True, check=True).stdout.split()
    names = {n for n in found if re.fullmatch(r"PURSUE_[A-Z0-9_]*[A-Z0-9]", n)}
    names -= {"PURSUE_ALLOWED", "PURSUE_EXCLUDED"}  # the lists themselves
    unclassified = names - set(PURSUE_ALLOWED) - set(PURSUE_EXCLUDED)
    assert not unclassified, f"classify these in tranche_autopilot/child_env.py: {unclassified}"


def test_the_storage_credentials_are_not_in_the_config_repr(tmp_path: Path) -> None:
    cfg = AutopilotConfig(SHA, tmp_path / "r.json", tmp_path, FakeRunner(tmp_path), {},
                          lambda _r: 0, storage_env={"R2_SECRET_ACCESS_KEY": "s3cr3t-value"})
    assert "s3cr3t-value" not in repr(cfg)



def test_a_local_url_rewrite_cannot_run_code_during_the_fetch(tmp_path: Path) -> None:
    """Real git: an insteadOf that rewrites the URL to ext:: or ssh is refused
    by the transport allowlist before anything runs (no network needed)."""
    import os

    from pursue_index.tranche_autopilot.child_env import FETCH_ENV, fetch_argv

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    marker = tmp_path / "ran"
    for rewrite in (f"ext::sh -c touch% {marker}", "ssh://git@example.invalid/"):
        subprocess.run(["git", "-C", str(repo), "config", "--replace-all",
                        f"url.{rewrite}.insteadOf", "https://github.com/"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "core.sshCommand", f"touch {marker}"],
                       check=True)
        done = subprocess.run(fetch_argv("BPSAI/pursue-index"), cwd=repo, capture_output=True,
                              text=True, timeout=30,
                              env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), **FETCH_ENV})
        assert done.returncode != 0 and "not allowed" in done.stderr, done.stderr
        assert not marker.exists()
        subprocess.run(["git", "-C", str(repo), "config", "--unset-all",
                        f"url.{rewrite}.insteadOf"], check=True)
