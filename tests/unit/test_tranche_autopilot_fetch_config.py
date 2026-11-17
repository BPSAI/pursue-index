"""Checkout config that can redirect or reshape the freshness fetch.

An empty ``url.<base>.insteadOf`` prefix rewrites every URL (git prepends the
base), and a local ``http.<url>.*`` key whose URL matches the pinned fetch URL
wins over the fetch's own ``-c`` overrides. Both are refused before the fetch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pursue_index.tranche_autopilot import ExitCode
from pursue_index.tranche_autopilot.child_env import fetch_argv
from pursue_index.tranche_autopilot.fetch_target import fetch_target_problem
from pursue_index.tranche_autopilot.gitops import GitError, local_http_keys
from pursue_index.tranche_autopilot.runner import CommandResult
from pursue_index.tranche_autopilot.urlmatch import config_url_applies
from tests.support.autopilot_fakes import FakeRunner, make_checkout, receipt, run_engine

_PINNED = "https://github.com/BPSAI/pursue-index.git"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _fetches(runner: FakeRunner) -> list[list[str]]:
    return [argv for argv in runner.calls if argv[0] == "git" and "fetch" in argv]


# -- empty insteadOf -------------------------------------------------------------

@pytest.mark.parametrize("prefix", ["", "   "])
def test_an_empty_insteadof_prefix_refuses(tmp_path: Path, prefix: str) -> None:
    """Real git: an empty prefix matches every URL, so git would fetch
    ``<base><pinned url>``. A blank one is refused too, failing closed."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "url.https://evil.invalid/x/.insteadOf", prefix)
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "insteadof" in doc["message"].lower()
    assert runner.release_calls() == [] and _fetches(runner) == []


# -- http.<url>.* ----------------------------------------------------------------

@pytest.mark.parametrize("config_url", [
    "https://github.com",
    "https://github.com/",
    "https://GitHub.com/",
    "https://github.com:443/",
    "https://github.com/BPSAI",
    "https://github.com/BPSAI/",
    "https://github.com/BPSAI/pursue-index.git",
    "https://*.com/",
    "https://user@github.com/",  # git skips it (the fetch URL has no user); refused anyway
])
def test_a_config_url_that_covers_the_fetch_applies(config_url: str) -> None:
    assert config_url_applies(config_url, _PINNED)


@pytest.mark.parametrize("config_url", [
    "http://github.com/",
    "https://gitlab.com/",
    "https://github.com:8443/",
    "https://github.com/BPS",
    "https://github.com/bpsai/",
    "https://github.com/BPSAI/pursue-index.git/x",
    "https://github.com/acme/",
    "https://*.github.com/",
])
def test_a_config_url_for_somewhere_else_does_not_apply(config_url: str) -> None:
    assert not config_url_applies(config_url, _PINNED)


def test_an_unparseable_config_url_applies_failing_closed() -> None:
    assert config_url_applies("not a url", _PINNED)


@pytest.mark.parametrize("config_url", [
    "https://github.com/x/../BPSAI/",          # git normalises this to /BPSAI/
    "https://github.com/./BPSAI",
    "https://github.com/acme/%2e%2e/BPSAI/",    # encoded dot segment
    "https://github.com/acme/%2E%2E",
    "https://github.com/BPSAI/pursue-index/..",
])
def test_a_config_url_with_dot_segments_applies_failing_closed(config_url: str) -> None:
    """git normalises dot segments before matching and this matcher doesn't, so
    any config path with one is treated as covering the fetch."""
    assert config_url_applies(config_url, _PINNED)


def test_a_dot_inside_a_path_name_is_not_a_dot_segment() -> None:
    assert not config_url_applies("https://github.com/acme/.config/", _PINNED)


def test_url_scoped_http_config_for_github_refuses(tmp_path: Path) -> None:
    """Real git: a local proxy with verification off could serve a forged main."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "http.https://github.com/.proxy", "http://127.0.0.1:9")
    _git(repo, "config", "http.https://github.com/.sslVerify", "false")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "http.https://github.com/.proxy" in doc["message"]
    assert "http.https://github.com/.sslverify" in doc["message"]
    assert runner.release_calls() == [] and _fetches(runner) == []


def test_general_local_http_config_refuses(tmp_path: Path) -> None:
    """Real git: a local http.curloptResolve plus http.sslCAInfo would send the
    fetch to another host that presents a certificate the checkout trusts."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "http.curloptResolve", "github.com:443:127.0.0.1")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "http.curloptresolve" in doc["message"]
    assert _fetches(runner) == []


def test_http_config_for_another_host_is_allowed(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "http.https://example.invalid/.proxy", "http://127.0.0.1:9")
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert _fetches(runner)


def test_the_fetch_forces_tls_verification_and_no_extra_headers() -> None:
    argv = fetch_argv("acme/widgets")
    pairs = {argv[i + 1] for i, a in enumerate(argv) if a == "-c"}
    assert "http.sslVerify=true" in pairs
    assert "http.extraHeader=" in pairs


# -- credential.<url>.* ----------------------------------------------------------

@pytest.mark.parametrize(("key", "value"), [
    ("credential.https://github.com.helper", "!touch pwned"),
    ("credential.https://github.com/BPSAI/.helper", "!touch pwned"),
    ("credential.https://github.com.username", "someone"),
    ("credential.helper", "!touch pwned"),
])
def test_local_credential_config_that_applies_to_the_fetch_refuses(
        tmp_path: Path, key: str, value: str) -> None:
    """Real git: a URL-scoped credential helper can run code during the fetch."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", key, value)
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "credential" in doc["message"]
    assert key in doc["message"]  # git keeps the URL as written; the rest is lowercase
    assert runner.release_calls() == [] and _fetches(runner) == []


def test_worktree_credential_config_refuses(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "extensions.worktreeConfig", "true")
    _git(repo, "config", "--worktree", "credential.https://github.com.helper", "!true")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "credential.https://github.com.helper" in doc["message"]
    assert _fetches(runner) == []


def test_credential_config_for_another_host_is_allowed(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "credential.https://example.invalid.helper", "!true")
    runner = FakeRunner(repo)
    code, _doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert _fetches(runner)


def test_the_fetch_clears_askpass() -> None:
    argv = fetch_argv("acme/widgets")
    pairs = {argv[i + 1] for i, a in enumerate(argv) if a == "-c"}
    assert "core.askPass=" in pairs
    assert "credential.helper=" in pairs


def test_the_local_config_readers_are_exported() -> None:
    from pursue_index.tranche_autopilot import gitops

    for name in ("local_url_rewrites", "local_http_keys", "local_credential_keys"):
        assert name in gitops.__all__
        assert callable(getattr(gitops, name))


# -- git too old for --show-scope ------------------------------------------------

_OLD_GIT = CommandResult(129, "", "error: unknown option `show-scope'\nusage: git config [<options>]\n")


def _old_git(argv, *, cwd, timeout, env=None) -> CommandResult:
    if argv[:2] == ["git", "config"]:
        return _OLD_GIT
    raise AssertionError(f"unexpected command: {argv}")


def test_git_without_show_scope_names_the_minimum_version(tmp_path: Path) -> None:
    with pytest.raises(GitError, match=r"git 2\.26 or newer"):
        local_http_keys(_old_git, tmp_path)
    problem = fetch_target_problem(_old_git, tmp_path, "BPSAI/pursue-index", None)
    assert problem is not None and "git 2.26 or newer" in problem


def test_another_config_failure_keeps_the_generic_error(tmp_path: Path) -> None:
    def broken(argv, *, cwd, timeout, env=None) -> CommandResult:
        return CommandResult(128, "", "fatal: bad config line 3")

    with pytest.raises(GitError, match="git config failed: fatal: bad config line 3"):
        local_http_keys(broken, tmp_path)


def test_refusals_never_echo_url_userinfo(tmp_path: Path) -> None:
    """Config keys can embed a URL's userinfo (a token); the refusal, which lands
    in the result JSON and logs, names the key with that part redacted."""
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "credential.https://someone:s3cr3t-token@github.com.helper", "x")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "s3cr3t-token" not in doc["message"] and "someone" not in doc["message"]
    assert "credential.https://***@github.com.helper" in doc["message"]
    assert _fetches(runner) == []


def test_insteadof_refusals_never_echo_url_userinfo(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _git(repo, "config", "url.https://someone:s3cr3t-token@evil.example/.insteadOf",
         "https://github.com/")
    runner = FakeRunner(repo)
    code, doc = run_engine(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "s3cr3t-token" not in doc["message"]
    assert _fetches(runner) == []
