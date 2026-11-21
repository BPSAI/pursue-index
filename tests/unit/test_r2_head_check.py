"""UBV1.3: a HEAD result is never proof of unchanged bytes; a stale weekly run fails the daily."""

from __future__ import annotations

import json
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _record(w: World, age_days: float, *, junk: bool = False) -> list[str]:
    when = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    row = {"schema": "pursue-full-hash-run/v1", "completed_at": when, "cards_hashed": 1,
           "bytes_hashed": 1, "drift_count": 0, "no_upstream_url": 0}
    w.record.write_text(("not json\n" if junk else "") + json.dumps(row) + "\n")
    return ["--run-record", str(w.record), "--max-full-hash-age-days", "8"]


def test_same_size_but_no_etag_is_fetched_and_hashed(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, etag='"e1"')
    w.head[w.cards[0]["asset_url"]] = (len(OLD_BODY), None)
    assert w.run() == 0
    assert w.fetched == [w.cards[0]["asset_url"]]


def test_same_size_and_a_changed_etag_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, etag='"e1"')
    w.head[w.cards[0]["asset_url"]] = (len(OLD_BODY), '"e2"')
    assert w.run() == 0
    assert len(w.fetched) == 1 and w.new_rows()[0]["byte_sha256"] == sha(NEW_BODY)


def test_a_head_error_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    w.head[w.cards[0]["asset_url"]] = (None, None)
    assert w.run() == 0
    assert len(w.fetched) == 1


def test_a_missing_size_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, etag='"e1"')
    w.head[w.cards[0]["asset_url"]] = (None, '"e1"')
    assert w.run() == 0
    assert len(w.fetched) == 1


def test_a_changed_size_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    w.head[w.cards[0]["asset_url"]] = (len(NEW_BODY), '"e1"')
    assert w.run() == 0
    assert len(w.fetched) == 1


def test_head_identical_is_reported_unverified_never_unchanged(w, capsys):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)  # HEAD matches; the bytes would differ
    assert w.run() == 0
    out = capsys.readouterr().out
    assert w.fetched == []
    assert "head-unchanged (unverified)=1" in out
    assert " unchanged=0" in out


def test_unchanged_is_only_ever_returned_with_a_computed_sha(w):
    """Every scenario: whenever a card is called unchanged, its bytes were fetched."""
    scenarios = {
        "match": (len(OLD_BODY), '"e1"'), "no-etag": (len(OLD_BODY), None),
        "no-size": (None, '"e1"'), "error": (None, None), "etag": (len(OLD_BODY), '"x"'),
    }
    for name, head in scenarios.items():
        w.fetched.clear()
        card = w.add_card(10 + len(name), prior=OLD_BODY, body=OLD_BODY)
        w.head[w.cards[-1]["asset_url"]] = head
        w.write()
        result = r2._process_card(
            SimpleNamespace(**w.cards[-1]), r2.load_registry(w.registry), object(), "b", True,
            w.registry, r2.RunState(),
        )
        assert result in ("unchanged", "head-unchanged"), (name, result)
        if result == "unchanged":
            assert w.fetched, f"{name}: called unchanged without fetching and hashing"
        assert card


def test_vid_cards_get_the_daily_head_check(w):
    w.add_card(1, "VID", ext="mp4", prior=OLD_BODY, body=OLD_BODY)
    assert w.run() == 0
    assert w.headed == [w.cards[0]["asset_url"]]


def test_aud_cards_get_the_daily_head_check(w):
    w.add_card(1, "AUD", ext="mp3", prior=OLD_BODY, body=OLD_BODY)
    assert w.run() == 0
    assert w.headed == [w.cards[0]["asset_url"]]


def test_a_nine_day_old_full_hash_record_fails_the_daily(w, capsys):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    flags = _record(w, 9)
    assert w.run(*flags) != 0
    assert "full-hash" in capsys.readouterr().err


def test_a_seven_day_old_full_hash_record_passes(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    assert w.run(*_record(w, 7)) == 0


def test_no_record_at_all_fails_the_daily(w, capsys):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    assert w.run("--run-record", str(w.record), "--max-full-hash-age-days", "8") != 0
    assert "no complete full-hash run" in capsys.readouterr().err


def test_the_newest_record_counts_and_junk_lines_are_skipped(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    flags = _record(w, 20, junk=True)
    old = w.record.read_text()
    fresh = json.loads(old.splitlines()[-1]) | {
        "completed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()
    }
    w.record.write_text(old + json.dumps(fresh) + "\n")
    assert w.run(*flags) == 0


def test_a_future_dated_record_does_not_count_as_fresh(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    assert w.run(*_record(w, -30)) != 0


def test_staleness_failure_comes_after_the_rows_are_written(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.head[w.cards[0]["asset_url"]] = (len(NEW_BODY), '"e2"')
    assert w.run(*_record(w, 30)) != 0
    assert len(w.new_rows()) == 1


def test_a_full_hash_run_does_not_check_staleness_of_itself(w):
    w.add_card(1, body=NEW_BODY)
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record),
               "--max-full-hash-age-days", "8")
    assert rc == 0


def test_staleness_check_needs_credentials_like_every_mode(w, capsys):
    w.add_card(1)
    w.creds = False
    assert w.run(*_record(w, 1)) != 0
    assert "credential" in capsys.readouterr().err.lower()


def test_daily_workflow_checks_the_weekly_record():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".github/workflows/verify-assets-daily.yml").read_text()
    assert "--max-full-hash-age-days 8" in text
    assert "--run-record" in text
