"""Round 3: the byte budget belongs to the full-hash pass only, and the local-fetch
override is scoped to a test, not a module global anyone can flip."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import _r2_hosts  # noqa: E402
from _r2_run_state import RunState  # noqa: E402


class _Manifest:
    cards: tuple = ()


def _args(*, full_hash: bool, budget: int | None) -> Namespace:
    return Namespace(full_hash=full_hash, max_bytes_per_run=budget)


def test_a_poll_lane_run_never_gets_a_byte_budget():
    state = RunState.for_run(_args(full_hash=False, budget=100), _Manifest(), frozenset(), "t")
    assert state.byte_budget is None


def test_a_poll_lane_fetch_over_the_budget_keeps_its_own_ceiling():
    # Even a state that somehow carries a budget must not cap a non-full-hash fetch.
    state = RunState(full_hash=False, byte_budget=100)
    state.bytes_hashed = 90
    assert state.fetch_ceiling(5_000_000) == 5_000_000


def test_the_full_hash_run_still_caps_each_fetch_to_the_budget_left():
    state = RunState.for_run(_args(full_hash=True, budget=1_000), _Manifest(), frozenset(), "t")
    state.bytes_hashed = 900
    assert state.fetch_ceiling(5_000_000) == 100


def test_the_local_fetch_override_is_not_a_module_global():
    assert not hasattr(_r2_hosts, "TEST_ONLY_ALLOW_LOCAL")


def test_plain_http_is_refused_unless_a_test_scopes_the_override():
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_hosts.check_scheme("http://127.0.0.1/x.pdf")
    with _r2_hosts.allow_local_for_tests():
        _r2_hosts.check_scheme("http://127.0.0.1/x.pdf")
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_hosts.check_scheme("http://127.0.0.1/x.pdf")
