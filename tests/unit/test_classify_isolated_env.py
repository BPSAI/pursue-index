"""The untrusted-PDF worker does not inherit the parent's secrets."""

from __future__ import annotations

import pytest

from pursue_index import classify_isolated


def test_worker_env_drops_unrelated_parent_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "do-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "do-not-leak")
    env = classify_isolated._env()
    assert "R2_SECRET_ACCESS_KEY" not in env and "GITHUB_TOKEN" not in env
    assert env["PYTHONPATH"]


def test_worker_env_keeps_what_the_interpreter_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = classify_isolated._env()
    assert env["PATH"] == "/usr/bin" and env["LANG"] == "C.UTF-8"
