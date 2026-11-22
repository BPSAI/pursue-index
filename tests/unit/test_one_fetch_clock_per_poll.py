"""One poll builds ONE manifest clock.

The snapshot path and the tranche-ready path both parse the same CSV. When
each stamped its own ``fetched_at``, marker timestamps and the release
window's upper year could disagree. The tests make the clock disagree between
calls (a later year every call) and assert a single value is used.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher
from tests.unit.test_tranche_ready_job_guard import _run  # also puts scripts/ on sys.path

import _tranche_ready_run  # noqa: E402


class _SteppingClock:
    """``datetime`` stand-in whose ``now()`` is a year later on every call."""

    calls = 0

    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        return datetime(2025 + cls.calls, 6, 1, tzinfo=UTC)


def test_snapshot_and_tranche_ready_share_one_fetched_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real = _tranche_ready_run.normalized_manifest

    def spy(*args, **kwargs):
        manifest = real(*args, **kwargs)
        seen.append(manifest.fetched_at.isoformat())
        return manifest

    monkeypatch.setattr(_tranche_ready_run, "normalized_manifest", spy)
    _SteppingClock.calls = 0
    # Seed the prior manifest with the real clock, then step it for the poll.
    out = tmp_path / "out"
    monkeypatch.setattr(csv_fetcher, "datetime", _SteppingClock)
    assert _run(tmp_path / "run", out, 3, monkeypatch) == 0

    snaps = [json.loads(p.read_text())
             for p in (tmp_path / "run" / "canonical").glob("*.json") if p.name != "index.json"]
    new_side = [m for m in snaps if len(m["cards"]) == 2]  # the prior has one card
    assert len(seen) == 1 and len(new_side) == 1
    assert datetime.fromisoformat(new_side[0]["fetched_at"]) == datetime.fromisoformat(seen[0])
