"""The freshness fetch's target and environment.

The fetch target is the public index, ``INDEX_SLUG``, overridable only by the
autopilot's own config or CLI -- never read from the checkout's git config. A
checkout whose ``origin`` (or a local URL rewrite) names another GitHub repo is
refused. The fetch runs with an empty temporary ``HOME`` so ``~/.netrc`` and
other home-directory config are out of reach.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from pursue_index.tranche_autopilot import ExitCode
from pursue_index.tranche_autopilot.child_env import (
    FETCH_ENV,
    INDEX_SLUG,
    fetch_argv,
    fetch_env,
)
from pursue_index.tranche_autopilot.runner import CommandResult, SubprocessRunner
from tests.support.autopilot_fakes import FakeRunner, make_checkout, receipt, run_engine

_PINNED = "https://github.com/BPSAI/pursue-index.git"
_REFSPEC = "+refs/heads/main:refs/remotes/origin/main"


def _fetches(runner: FakeRunner) -> list[list[str]]:
    return [argv for argv in runner.calls if argv[0] == "git" and "fetch" in argv]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


# -- unit: the slug and the env ------------------------------------------------

def test_the_pinned_slug_is_the_public_index() -> None:
    assert INDEX_SLUG == "BPSAI/pursue-index"


def test_fetch_argv_fetches_the_named_repo_over_https() -> None:
    assert fetch_argv("acme/widgets")[-2:] == ["https://github.com/acme/widgets.git", _REFSPEC]


def test_the_fetch_env_has_an_isolated_home_and_no_prompt() -> None:
    env = fetch_env({"PATH": "/bin", "HOME": "/home/someone"}, "/tmp/empty-home")
    assert env["HOME"] == "/tmp/empty-home"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["PATH"] == "/bin"
    for key, value in FETCH_ENV.items():
        assert env[key] == value


# -- engine: where the target comes from -----------------------------------------

def test_a_non_github_origin_still_fetches_the_pinned_index(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", "https://example.invalid/mirror/index.git")
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert _fetches(runner)[0][-2:] == [_PINNED, _REFSPEC]


def test_a_matching_origin_is_compared_case_insensitively(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", "git@github.com:bpsai/Pursue-Index.git")
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert _fetches(runner)[0][-2:] == [_PINNED, _REFSPEC]


def test_a_checkout_whose_origin_is_another_repo_refuses(tmp_path: Path) -> None:
    """Real git: the origin names another GitHub repo, so nothing runs."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", "git@github.com:acme/widgets.git")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "acme/widgets" in doc["message"] and INDEX_SLUG in doc["message"]
    assert runner.release_calls() == [] and _fetches(runner) == []


def test_a_local_rewrite_of_the_origin_to_another_repo_refuses(tmp_path: Path) -> None:
    """Real git: origin says the index, but a local insteadOf points it elsewhere."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", _PINNED)
    _git(repo, "config", "url.https://github.com/acme/widgets.git.insteadOf", _PINNED)
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "acme/widgets" in doc["message"] or "insteadof" in doc["message"].lower()
    assert runner.release_calls() == [] and _fetches(runner) == []


def test_a_local_rewrite_of_the_pinned_url_refuses(tmp_path: Path) -> None:
    """Real git: no GitHub origin, but a local insteadOf would redirect the
    pinned fetch URL itself to another repo's main."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "url.https://github.com/acme/widgets.insteadOf",
         "https://github.com/BPSAI/")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "insteadof" in doc["message"].lower()
    assert _fetches(runner) == []


def test_the_expected_repo_is_set_by_the_autopilot_config(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner, expected_slug="acme/widgets")
    assert code == ExitCode.DONE
    assert _fetches(runner)[0][-2:] == ["https://github.com/acme/widgets.git", _REFSPEC]


@pytest.mark.parametrize("slug", ["", "acme", "acme/../x", "acme/wid;gets", "a/b/c"])
def test_a_malformed_expected_repo_is_refused(tmp_path: Path, slug: str) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner, expected_slug=slug)
    assert code == ExitCode.PRECONDITION
    assert runner.release_calls() == []


def test_an_origin_changed_during_the_run_fails_the_recheck(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "remote", "add", "origin", _PINNED)
    runner = FakeRunner(repo)

    def retarget(argv: Sequence[str], cwd: Path) -> CommandResult:
        _git(repo, "remote", "set-url", "origin", "https://github.com/acme/widgets.git")
        return CommandResult(0, "passed")

    runner.handlers[("npm", "run", "test")] = retarget
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "freshness-recheck"
    assert "acme/widgets" in doc["message"]
    assert _fetches(runner) == []


# -- the fetch environment -------------------------------------------------------

def test_only_the_fetch_gets_a_fresh_empty_home(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    real_home = tmp_path / "home"
    real_home.mkdir()
    seen: dict[str, object] = {}

    class Recording(FakeRunner):
        def __call__(self, argv: Sequence[str], *, cwd: Path, timeout: float,
                     env: Mapping[str, str] | None = None) -> CommandResult:
            if argv[0] == "git" and "fetch" in argv:
                home = Path(env["HOME"])
                seen.update(home=home, existed=home.is_dir(), listing=list(home.iterdir()),
                            env=dict(env))
            return super().__call__(argv, cwd=cwd, timeout=timeout, env=env)

    runner = Recording(repo)
    code, _doc = run_engine(tmp_path, repo, runner, env={"HOME": str(real_home)})
    assert code == ExitCode.DONE
    home = seen["home"]
    assert home != real_home and seen["existed"] and seen["listing"] == []
    assert not home.exists()  # cleaned up after the fetch
    fetch_env_seen = seen["env"]
    assert fetch_env_seen["GIT_TERMINAL_PROMPT"] == "0"
    assert fetch_env_seen["GIT_CONFIG_NOSYSTEM"] == "1"
    assert fetch_env_seen["GIT_CONFIG_GLOBAL"] == "/dev/null"
    others = [e for a, e in zip(runner.calls, runner.envs, strict=True)
              if a[0] != "git" and e is not None]
    assert others and all(e.get("HOME") == str(real_home) for e in others)
    assert all("GIT_TERMINAL_PROMPT" not in e for e in others)


def test_a_netrc_in_the_real_home_is_not_visible_to_the_fetch(tmp_path: Path) -> None:
    """Real process: the fetch child is a ``git`` shim on PATH that records the
    HOME it was given and whether a ``.netrc`` is there, then fails like an
    unreachable remote -- so no network is needed and the step fails closed."""
    repo = make_checkout(tmp_path, receipt())
    real_home = tmp_path / "home"
    real_home.mkdir()
    (real_home / ".netrc").write_text("machine github.com login x password planted\n")
    record = tmp_path / "seen"
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        f'{{ echo "HOME=$HOME"; echo "PROMPT=$GIT_TERMINAL_PROMPT"; '
        f'[ -e "$HOME/.netrc" ] && echo NETRC=yes || echo NETRC=no; }} > "{record}"\n'
        "echo 'fatal: unable to access remote' >&2\nexit 128\n")
    shim.chmod(0o755)

    class RealFetch(FakeRunner):
        def __call__(self, argv: Sequence[str], *, cwd: Path, timeout: float,
                     env: Mapping[str, str] | None = None) -> CommandResult:
            if argv[0] == "git" and "fetch" in argv:
                self.calls.append(list(argv))
                return SubprocessRunner()(argv, cwd=cwd, timeout=timeout, env=env)
            return super().__call__(argv, cwd=cwd, timeout=timeout, env=env)

    runner = RealFetch(repo)
    env = {"HOME": str(real_home), "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"}
    code, doc = run_engine(tmp_path, repo, runner, env=env)
    lines = dict(line.split("=", 1) for line in record.read_text().split())
    assert lines["NETRC"] == "no"
    assert lines["PROMPT"] == "0"
    assert lines["HOME"] != str(real_home) and not Path(lines["HOME"]).exists()
    assert code == ExitCode.GATE_FAILED and doc["failed_step"] == "freshness-recheck"
    assert "planted" not in str(doc)


# -- CLI ------------------------------------------------------------------------

def test_the_cli_passes_the_expected_repo_to_the_engine(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from pursue_index.cli.commands import app
    from pursue_index.tranche_autopilot import engine

    captured = {}

    def fake_run(cfg):
        captured["cfg"] = cfg
        return int(ExitCode.DONE)

    monkeypatch.setattr(engine, "run_autopilot", fake_run)
    base = ["tranche", "autopilot", "--tranche", "ab" * 32,
            "--result", str(tmp_path / "r.json"), "--repo-root", str(tmp_path)]
    CliRunner().invoke(app, base)
    assert captured["cfg"].expected_slug == INDEX_SLUG
    CliRunner().invoke(app, [*base, "--expected-repo", "acme/widgets"])
    assert captured["cfg"].expected_slug == "acme/widgets"
