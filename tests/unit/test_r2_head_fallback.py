"""UBV P1-1: without an ETag, HEAD identity falls back to Content-Length + Last-Modified."""

from __future__ import annotations

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, sha

LM = "Wed, 01 Jul 2026 00:00:00 GMT"


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _url(w: World) -> str:
    return w.cards[0]["asset_url"]


def test_no_etag_same_length_and_last_modified_is_not_refetched(w, capsys):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, etag=None, last_modified=LM)
    assert w.run() == 0
    out = capsys.readouterr().out
    assert w.fetched == []
    assert "head-unchanged (unverified)=1" in out and " unchanged=0" in out


def test_no_etag_and_a_different_last_modified_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, etag=None, last_modified=LM)
    w.head[_url(w)] = (len(OLD_BODY), None, "Thu, 02 Jul 2026 00:00:00 GMT")
    assert w.run() == 0
    assert w.fetched == [_url(w)]
    assert w.new_rows()[0]["byte_sha256"] == sha(NEW_BODY)


def test_no_etag_and_no_last_modified_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, etag=None, last_modified=LM)
    w.head[_url(w)] = (len(OLD_BODY), None, None)
    assert w.run() == 0
    assert w.fetched == [_url(w)]


def test_an_older_row_without_last_modified_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, etag=None)
    w.head[_url(w)] = (len(OLD_BODY), None, LM)
    assert w.run() == 0
    assert w.fetched == [_url(w)]


def test_no_etag_and_a_changed_length_is_fetched(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, etag=None, last_modified=LM)
    w.head[_url(w)] = (len(NEW_BODY), None, LM)
    assert w.run() == 0
    assert w.fetched == [_url(w)]


def test_a_differing_etag_is_not_rescued_by_last_modified(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, etag='"e1"', last_modified=LM)
    w.head[_url(w)] = (len(OLD_BODY), '"e2"', LM)
    assert w.run() == 0
    assert w.fetched == [_url(w)]


def test_the_weekly_full_hash_fetches_whatever_head_says(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, etag=None, last_modified=LM)
    rc = w.run("--full-hash", "--max-bytes-per-run", "1000",
               "--run-record", str(w.tmp / "rec.jsonl"))
    assert rc == 0
    assert w.fetched == [_url(w)]


def test_a_new_row_records_last_modified(w):
    w.add_card(1, body=NEW_BODY)
    w.head[_url(w)] = (len(NEW_BODY), None, LM)
    assert w.run() == 0
    assert w.new_rows()[0]["upstream_last_modified"] == LM
