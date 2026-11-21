"""UBV1.1: ``--full-hash`` hashes every published asset under a loud byte budget."""

from __future__ import annotations

import json

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _args(w: World, budget: int = 1_000_000) -> list[str]:
    return ["--full-hash", "--max-bytes-per-run", str(budget), "--run-record", str(w.record)]


def test_same_head_but_different_bytes_appends_a_row(w, capsys):
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY)  # HEAD matches the prior row
    assert w.run(*_args(w)) == 0
    rows = w.new_rows()
    assert [r["card_id"] for r in rows] == [cid]
    assert rows[0]["byte_sha256"] == sha(NEW_BODY)


def test_without_full_hash_the_same_setup_appends_nothing(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    r2_rc = w.run("--run-record", str(w.record))
    assert r2_rc == 0 and w.new_rows() == []


def test_vid_and_aud_cards_are_hashed(w):
    vid = w.add_card(2, "VID", ext="mp4", prior=OLD_BODY, body=NEW_BODY)
    aud = w.add_card(3, "AUD", ext="mp3", prior=OLD_BODY, body=NEW_BODY)
    img = w.add_card(4, "IMG", ext="jpg", prior=OLD_BODY, body=NEW_BODY)
    assert w.run(*_args(w)) == 0
    assert sorted(r["card_id"] for r in w.new_rows()) == sorted([vid, aud, img])
    assert len(w.fetched) == 3


def test_budget_exceeded_fails_counts_unhashed_and_writes_no_record(w, capsys):
    for n in (1, 2, 3):
        w.add_card(n, prior=b"x" * 100, body=b"y" * 100)
    rc = w.run(*_args(w, budget=150))
    out = capsys.readouterr()
    assert rc != 0
    assert "2 card(s) left unhashed" in out.out + out.err
    assert not w.record.exists()
    assert len(w.fetched) == 1, "the second card would overshoot the budget, so it is not fetched"


def test_budget_exceeded_by_actual_bytes_still_fails(w, capsys):
    for n in (1, 2, 3):
        w.add_card(n, body=b"y" * 100)  # no prior row: size unknown until fetched
    rc = w.run(*_args(w, budget=150))
    out = capsys.readouterr()
    assert rc != 0 and "1 card(s) left unhashed" in out.out + out.err
    assert not w.record.exists()


def test_exactly_at_budget_is_complete(w):
    w.add_card(1, body=b"y" * 100)
    w.add_card(2, body=b"y" * 100)
    assert w.run(*_args(w, budget=200)) == 0
    assert w.record.exists()


def test_max_bytes_per_run_is_required_in_full_hash_mode(w):
    w.add_card(1)
    with pytest.raises(SystemExit) as exc:
        w.run("--full-hash")
    assert exc.value.code != 0


def test_a_complete_run_writes_a_dated_record(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    w.add_card(2, prior=NEW_BODY, body=NEW_BODY)
    w.add_card(3, body=NEW_BODY)  # net-new: not drift
    assert w.run(*_args(w)) == 0
    rec = [json.loads(ln) for ln in w.record.read_text().splitlines()]
    assert len(rec) == 1
    assert rec[0]["cards_hashed"] == 3
    assert rec[0]["bytes_hashed"] == 3 * len(NEW_BODY)
    assert rec[0]["drift_count"] == 1
    assert rec[0]["completed_at"].startswith("20")


def test_a_fetch_failure_means_no_complete_record(w, monkeypatch):
    w.add_card(1, body=NEW_BODY)

    def boom(u, dest):
        raise OSError("down")

    monkeypatch.setattr(r2, "fetch_asset", boom)
    assert w.run(*_args(w)) != 0
    assert not w.record.exists()


def test_a_limited_run_is_never_recorded_as_complete(w):
    w.add_card(1)
    w.add_card(2)
    assert w.run(*_args(w), "--limit", "1") != 0
    assert not w.record.exists()


def test_dry_run_full_hash_writes_no_record_and_no_rows(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    assert w.run(*_args(w), "--dry-run") == 0
    assert w.new_rows() == [] and not w.record.exists()


def test_missing_credentials_fail_closed_in_the_weekly_full_hash(w, capsys):
    w.add_card(1)
    w.creds = False
    assert w.run(*_args(w)) != 0
    assert "credential" in (capsys.readouterr().err).lower()
    assert not w.record.exists()


def test_missing_credentials_are_fine_under_dry_run(w):
    w.add_card(1)
    w.creds = False
    assert w.run("--dry-run") == 0


def test_dvids_hosted_cards_without_a_url_are_counted_not_ignored(w, capsys):
    w.add_card(1, body=NEW_BODY)
    w.cards.append({
        "card_id": "00000000000000aa", "title": "v", "asset_type": "VID", "agency": "A",
    })
    assert w.run(*_args(w)) == 0
    out = capsys.readouterr().out
    assert "no-upstream-url=1" in out
    assert json.loads(w.record.read_text().splitlines()[0])["no_upstream_url"] == 1
