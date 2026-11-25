"""The fetch ceiling is the higher of the configured maximum and the asset's measured one."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha  # noqa: E402

pytestmark = pytest.mark.usefixtures("dns")

MIB = 1024**2


def _world(tmp_path, monkeypatch, known, new_size):
    """One card whose recorded size is ``known``; its fetch reads ``new_size`` bytes (simulated:
    the seam enforces ``max_bytes`` the way ``fetch_asset`` does, then writes a small body)."""
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.rows[0]["byte_size"] = known
    limits = []

    def fetch(u, dest, **kw):
        limits.append(kw["max_bytes"])
        if new_size > kw["max_bytes"]:
            raise _r2_fetch.FetchOverCapError(observed=new_size, cap=kw["max_bytes"], declared=True)
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), new_size

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    return w, limits


def test_a_small_asset_that_grew_past_three_times_is_fetched_and_recorded(tmp_path, monkeypatch, capsys):
    known = 20 * MIB  # 10x is 200 MiB, below the configured maximum
    new = 300 * MIB  # more than 3x the old size, below MAX_ASSET_BYTES
    assert 3 * known < new < _r2_fetch.MAX_ASSET_BYTES
    w, limits = _world(tmp_path, monkeypatch, known, new)
    w.run()
    assert limits == [_r2_fetch.MAX_ASSET_BYTES]
    assert "fail=0" in capsys.readouterr().out
    assert [r["byte_sha256"] for r in w.new_rows()] == [sha(NEW_BODY)]


def test_an_asset_above_both_ceilings_still_fails_its_card(tmp_path, monkeypatch, capsys):
    w, _ = _world(tmp_path, monkeypatch, 20 * MIB, _r2_fetch.MAX_ASSET_BYTES + 1)
    w.run()
    assert "fail=1" in capsys.readouterr().out
    assert w.new_rows() == []


def test_a_big_asset_keeps_its_own_measured_ceiling():
    known = 3_212_900_000
    ceiling = _r2_fetch.hard_ceiling([{"byte_size": known}])
    assert ceiling == known * _r2_fetch.HARD_GROWTH_FACTOR > _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.hard_ceiling([{"byte_size": 1}]) >= _r2_fetch.MAX_ASSET_BYTES
