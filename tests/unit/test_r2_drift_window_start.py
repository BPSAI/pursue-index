"""Where the registry drift window starts: never after rows a failed weekly run wrote."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha

import _r2_run_state  # noqa: E402  (scripts/ is on sys.path via the harness)

BOOTSTRAP_WINDOW_DAYS = _r2_run_state.BOOTSTRAP_WINDOW_DAYS


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _args(tmp_path, *, marker=None, record=None):
    reg = tmp_path / "registry.jsonl"
    return SimpleNamespace(
        registry=reg, gate_marker=marker or tmp_path / "m.jsonl",
        run_record=record or tmp_path / "r.jsonl",
    )


def _write(path, **row):
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def test_the_window_starts_at_the_earliest_of_marker_and_weekly_record(tmp_path):
    a = _args(tmp_path)
    _write(a.gate_marker, completed_at=_ago(1).isoformat())
    _write(a.run_record, completed_at=_ago(3).isoformat(), started_at=_ago(3.1).isoformat())
    assert abs(r2.drift_window_start(a) - _ago(3.1)) < timedelta(seconds=5)


def test_a_marker_older_than_the_weekly_record_wins(tmp_path):
    a = _args(tmp_path)
    _write(a.gate_marker, completed_at=_ago(5).isoformat())
    _write(a.run_record, completed_at=_ago(1).isoformat(), started_at=_ago(1.1).isoformat())
    assert abs(r2.drift_window_start(a) - _ago(5)) < timedelta(seconds=5)


def test_a_weekly_record_alone_starts_at_when_that_run_began(tmp_path):
    a = _args(tmp_path)
    _write(a.run_record, completed_at=_ago(2).isoformat(), started_at=_ago(2.2).isoformat())
    assert abs(r2.drift_window_start(a) - _ago(2.2)) < timedelta(seconds=5)


def test_a_legacy_record_without_a_start_is_not_trusted_past_the_bootstrap_window(tmp_path):
    a = _args(tmp_path)
    _write(a.run_record, completed_at=_ago(1).isoformat())
    assert abs(r2.drift_window_start(a) - _ago(BOOTSTRAP_WINDOW_DAYS)) < timedelta(seconds=5)


def test_with_neither_the_bootstrap_window_applies(tmp_path):
    assert abs(r2.drift_window_start(_args(tmp_path)) - _ago(BOOTSTRAP_WINDOW_DAYS)) < timedelta(seconds=5)


def test_a_complete_weekly_record_carries_its_start(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    assert w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record)) == 0
    row = json.loads(w.record.read_text().splitlines()[-1])
    assert datetime.fromisoformat(row["started_at"]) <= datetime.fromisoformat(row["completed_at"])


def test_a_failed_weekly_that_wrote_drift_rows_is_still_caught_by_the_next_daily(w, capsys):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    # The weekly writes the drift row and its complete-run record, then fails the drift gate.
    assert w.run("--full-hash", "--max-bytes-per-run", "1000", *flags) != 0
    marker = w.tmp / "drift-gate-passes.jsonl"
    assert w.record.exists() and not marker.exists()
    capsys.readouterr()
    # The daily: no marker, the row is now the registry's latest and HEAD agrees with it.
    w.rows = w.registry_rows()
    w.head[w.cards[0]["asset_url"]] = (len(NEW_BODY), '"e1"')
    assert w.run(*flags) != 0
    err = capsys.readouterr().err
    assert cid in err and sha(OLD_BODY) in err and sha(NEW_BODY) in err
