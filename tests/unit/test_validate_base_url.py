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


def _budget(monkeypatch, *, job=40, build=1200, stamp=300, margin=120):
    """Set the budget inputs the workflow passes: 40 min - 1200 - 300 - 120 = 780s of cap."""
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.setenv("JOB_TIMEOUT_MINUTES", str(job))
    monkeypatch.setenv("BUILD_WAIT_SECS", str(build))
    monkeypatch.setenv("STAMP_WAIT_SECS", str(stamp))
    monkeypatch.setenv("FAILURE_ISSUE_MARGIN_SECS", str(margin))


def test_the_cap_is_derived_from_the_budget_parts():
    assert mod.wait_cap_secs(40, 1200, 300, 120) == 780
    assert mod.wait_cap_secs(60, 1200, 300, 120) == 1980


def test_max_wait_above_the_derived_cap_is_refused_with_a_clear_message(monkeypatch, capsys):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS", "781")
    assert mod.main([]) == 1
    err = capsys.readouterr().err
    assert "781" in err and "780" in err and "timeout" in err


@pytest.mark.parametrize("v", ["780", "600", "0"])
def test_max_wait_at_or_below_the_derived_cap_passes(monkeypatch, v):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS", v)
    assert mod.main([]) == 0


def test_the_cap_follows_the_budget_not_a_constant(monkeypatch):
    _budget(monkeypatch, job=60)  # a longer job allows a longer wait
    monkeypatch.setenv("MAX_WAIT_SECS", "1980")
    assert mod.main([]) == 0
    monkeypatch.setenv("MAX_WAIT_SECS", "1981")
    assert mod.main([]) == 1


def test_a_hand_set_cap_variable_is_ignored(monkeypatch):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS_CAP", "99999")
    monkeypatch.setenv("MAX_WAIT_SECS", "781")
    assert mod.main([]) == 1


@pytest.mark.parametrize("name", ["JOB_TIMEOUT_MINUTES", "BUILD_WAIT_SECS", "STAMP_WAIT_SECS",
                                  "FAILURE_ISSUE_MARGIN_SECS"])
@pytest.mark.parametrize("bad", ["lots", ""])
def test_a_malformed_budget_part_is_an_error(monkeypatch, name, bad):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS", "10")
    monkeypatch.setenv(name, bad)
    assert mod.main([]) == 1


def test_a_partly_given_budget_is_an_error(monkeypatch):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS", "10")
    monkeypatch.delenv("STAMP_WAIT_SECS")
    assert mod.main([]) == 1


def test_a_budget_that_leaves_no_room_is_an_error(monkeypatch):
    _budget(monkeypatch, job=10)  # 600s less 1200 + 300 + 120
    monkeypatch.setenv("MAX_WAIT_SECS", "0")
    assert mod.main([]) == 1


@pytest.mark.parametrize("v,ok", [("600", True), ("0", True), ("6;rm", False), ("", False), ("-1", False)])
def test_max_wait_validation(monkeypatch, v, ok):
    _budget(monkeypatch)
    monkeypatch.setenv("MAX_WAIT_SECS", v)
    assert (mod.main([]) == 0) is ok


def test_max_wait_without_any_budget_is_refused_not_skipped(monkeypatch, capsys):
    """A max wait with no budget at all must fail closed, not skip the cap check."""
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    for k in mod.BUDGET_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MAX_WAIT_SECS", "600")
    assert mod.main([]) == 1
    assert "wait budget is missing" in capsys.readouterr().err


def test_base_url_alone_needs_no_budget(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://pursueindex.com")
    monkeypatch.delenv("MAX_WAIT_SECS", raising=False)
    for k in mod.BUDGET_ENV:
        monkeypatch.delenv(k, raising=False)
    assert mod.main([]) == 0
