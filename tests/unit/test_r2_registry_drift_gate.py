"""UBV round 3: the drift gate reads the registry, so a poll-written drift row is caught."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, sha


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _poll_row(w: World, cid: str, body: bytes, days_ago: float) -> None:
    """A row the poll lane appended (no --fail-on-drift), and HEAD now matches it."""
    prior = next(r for r in w.rows if r["card_id"] == cid)
    w.rows.append({
        **prior, "byte_sha256": sha(body), "byte_size": len(body),
        "archive_key": f"archive/{sha(body)}.pdf", "fetched_at": _ago(days_ago),
    })
    w.head[prior["asset_url"]] = (len(body), '"e1"')


def _flags(w: World) -> list[str]:
    return ["--fail-on-drift", "--dispositions", str(w.dispositions),
            "--run-record", str(w.record)]


def _disposition(w: World, cid: str) -> None:
    w.dispositions.write_text(json.dumps({
        "card_id": cid, "old_sha256": sha(OLD_BODY), "new_sha256": sha(NEW_BODY),
        "disposition": "resave-content-verified", "reviewed_at": "2026-11-21",
        "evidence": "re-save, same content", "evidence_ref": "3" * 64,
        "ocr_from": sha(OLD_BODY),
    }) + "\n")


def _complete_run(w: World, days_ago: float) -> None:
    w.record.write_text(
        json.dumps({"started_at": _ago(days_ago + 0.01), "completed_at": _ago(days_ago)}) + "\n"
    )


def test_a_poll_written_drift_row_fails_the_gate(w, capsys):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=1)
    assert w.run(*_flags(w)) != 0
    err = capsys.readouterr().err
    assert cid in err and sha(OLD_BODY) in err and sha(NEW_BODY) in err


def test_a_poll_written_drift_row_with_a_disposition_passes(w):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=1)
    _disposition(w, cid)
    assert w.run(*_flags(w)) == 0


def test_a_net_new_cards_first_row_passes(w):
    cid = w.add_card(1, body=NEW_BODY)  # no prior: this run writes its first row
    assert w.run(*_flags(w)) == 0
    assert [r["card_id"] for r in w.new_rows()] == [cid]


def test_a_net_new_card_first_row_from_the_poll_lane_passes(w):
    cid = w.add_card(1, prior=NEW_BODY, body=NEW_BODY)
    w.rows[0]["fetched_at"] = _ago(1)
    assert cid and w.run(*_flags(w)) == 0


def test_rows_older_than_the_previous_complete_run_are_ignored(w):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=3)
    _complete_run(w, days_ago=2)  # the run after the drift row
    assert w.run(*_flags(w)) == 0


def test_a_row_after_the_previous_complete_run_is_caught(w):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=1)
    _complete_run(w, days_ago=2)
    assert w.run(*_flags(w)) != 0


def test_with_no_previous_run_only_the_last_eight_days_are_checked(w):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=9)
    assert w.run(*_flags(w)) == 0


def test_a_passing_gate_leaves_a_marker_and_a_failing_one_does_not(w):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    _poll_row(w, cid, NEW_BODY, days_ago=1)
    marker = w.tmp / "drift-gate-passes.jsonl"
    assert w.run(*_flags(w)) != 0
    assert not marker.exists(), "a failed gate must be rescanned next time"
    _disposition(w, cid)
    assert w.run(*_flags(w)) == 0
    assert marker.exists()
