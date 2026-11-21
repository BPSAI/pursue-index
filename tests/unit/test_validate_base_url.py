"""``scripts/validate_base_url.py``: the workflow_dispatch base_url allowlist."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_base_url.py"
spec = importlib.util.spec_from_file_location("validate_base_url", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.mark.parametrize("url", ["https://pursueindex.com", "https://pursueindex.com/", "https://www.pursueindex.com"])
def test_allowed(url):
    assert mod.validate(url) is None


@pytest.mark.parametrize("url", [
    "https://evil.example", "http://pursueindex.com", "https://user@pursueindex.com",
    "https://user:pw@pursueindex.com", "https://pursueindex.com:8443", "https://pursueindex.com/a",
    "https://pursueindex.com.evil.example", "https://pursueindex.com?x=1", "https://pursueindex.com/#f",
    "https://pursueindex.com\n", "", "pursueindex.com",
])
def test_rejected(url):
    assert mod.validate(url)


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setenv("BASE_URL", "https://evil.example")
    assert mod.main([]) == 1
    assert "BASE_URL" in capsys.readouterr().err
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    assert mod.main([]) == 0


@pytest.mark.parametrize("v,ok", [("600", True), ("0", True), ("6;rm", False), ("", False), ("-1", False)])
def test_max_wait_validation(monkeypatch, v, ok):
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.setenv("MAX_WAIT_SECS", v)
    assert (mod.main([]) == 0) is ok


def test_max_wait_above_the_cap_is_refused_with_a_clear_message(monkeypatch, capsys):
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.setenv("MAX_WAIT_SECS_CAP", "780")
    monkeypatch.setenv("MAX_WAIT_SECS", "781")
    assert mod.main([]) == 1
    err = capsys.readouterr().err
    assert "781" in err and "780" in err and "timeout" in err


@pytest.mark.parametrize("v", ["780", "600", "0"])
def test_max_wait_at_or_below_the_cap_passes(monkeypatch, v):
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.setenv("MAX_WAIT_SECS_CAP", "780")
    monkeypatch.setenv("MAX_WAIT_SECS", v)
    assert mod.main([]) == 0


def test_a_malformed_cap_is_an_error(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.setenv("MAX_WAIT_SECS_CAP", "lots")
    monkeypatch.setenv("MAX_WAIT_SECS", "10")
    assert mod.main([]) == 1
