"""``scripts/check_deployed_commit.py``: the live site was built from this push."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_deployed_commit.py"
SHA = "b" * 40
OTHER = "c" * 40


def _load():
    spec = importlib.util.spec_from_file_location("check_deployed_commit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def wait(stamps, timeout=30):
    queue = list(stamps)
    now = [0.0]

    def fetch(url):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return mod.wait_for_commit(fetch, sha=SHA, timeout_secs=timeout, interval_secs=10,
                               sleep=lambda s: now.__setitem__(0, now[0] + s),
                               clock=lambda: now[0])


def test_match_passes():
    ok, msg = wait([{"commit": SHA}])
    assert ok, msg


def test_mismatch_fails_after_timeout():
    ok, msg = wait([{"commit": OTHER}])
    assert not ok and OTHER in msg and SHA in msg


def test_missing_field_fails():
    ok, msg = wait([{"schema": "x"}])
    assert not ok and "commit" in msg


def test_non_object_stamp_fails():
    ok, _ = wait([["not", "an", "object"]])
    assert not ok


def test_fetch_error_fails_after_timeout():
    ok, _ = wait([OSError("404")])
    assert not ok


def test_stale_then_fresh_passes():
    ok, msg = wait([{"commit": OTHER}, {"commit": SHA}])
    assert ok, msg


def test_stamp_url_has_cache_buster():
    assert mod.stamp_url("https://pursueindex.com/", 7).startswith("https://pursueindex.com/deploy-stamp.json?")
