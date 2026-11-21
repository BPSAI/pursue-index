"""UBV1.2: byte drift on a published card fails the verify, after the rows are written."""

from __future__ import annotations

import json

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, card_id, sha


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _drifted(w: World, n: int = 1) -> str:
    # HEAD reports a different size, so the daily check fetches; bytes differ.
    cid = w.add_card(n, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.head[w.cards[-1]["asset_url"]] = (len(NEW_BODY), '"e2"')
    return cid


def _disposition(w: World, cid: str, kind: str = "resave-content-verified") -> None:
    w.dispositions.write_text(json.dumps({
        "card_id": cid, "old_sha256": sha(OLD_BODY), "new_sha256": sha(NEW_BODY),
        "disposition": kind, "reviewed_at": "2026-11-21", "evidence": "re-save, same content",
        "evidence_ref": "3" * 64, "ocr_from": sha(OLD_BODY),
    }) + "\n")


def _flags(w: World) -> list[str]:
    return ["--fail-on-drift", "--dispositions", str(w.dispositions)]


def test_drift_fails_names_the_card_and_both_shas_and_keeps_the_rows(w, capsys):
    cid = _drifted(w)
    rc = w.run(*_flags(w))
    err = capsys.readouterr().err
    assert rc != 0
    assert cid in err and sha(OLD_BODY) in err and sha(NEW_BODY) in err
    assert [r["card_id"] for r in w.new_rows()] == [cid], "rows are written before the failure"


def test_a_matching_resave_disposition_does_not_fail(w):
    cid = _drifted(w)
    _disposition(w, cid)
    assert w.run(*_flags(w)) == 0
    assert len(w.new_rows()) == 1


def test_a_content_changed_disposition_does_not_cover(w):
    cid = _drifted(w)
    _disposition(w, cid, "content-changed")
    assert w.run(*_flags(w)) != 0


def test_a_disposition_for_other_bytes_does_not_cover(w):
    cid = _drifted(w)
    w.dispositions.write_text(json.dumps({
        "card_id": cid, "old_sha256": sha(OLD_BODY), "new_sha256": "e" * 64,
        "disposition": "resave-content-verified", "reviewed_at": "2026-11-21",
        "evidence": "x", "evidence_ref": "3" * 64, "ocr_from": sha(OLD_BODY),
    }) + "\n")
    assert w.run(*_flags(w)) != 0


def test_a_net_new_card_does_not_fail(w):
    w.add_card(1, body=NEW_BODY)  # no prior registry row
    assert w.run(*_flags(w)) == 0
    assert len(w.new_rows()) == 1


def test_only_the_uncovered_card_is_named(w, capsys):
    covered, bare = _drifted(w, 1), _drifted(w, 2)
    _disposition(w, covered)
    rc = w.run(*_flags(w))
    err = capsys.readouterr().err
    assert rc != 0 and bare in err and covered not in err


def test_without_the_flag_drift_does_not_fail(w):
    # The poll lane runs without it: rows must still be committed after a clean exit.
    _drifted(w)
    assert w.run() == 0


def test_malformed_dispositions_fail_closed(w):
    _drifted(w)
    w.dispositions.write_text("{nope\n")
    assert w.run(*_flags(w)) != 0


def test_full_hash_drift_also_fails(w):
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY)
    rc = w.run(*_flags(w), "--full-hash", "--max-bytes-per-run", "1000000")
    assert rc != 0


def test_unchanged_bytes_never_count_as_drift(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    w.head[w.cards[-1]["asset_url"]] = (999, '"other"')
    assert w.run(*_flags(w)) == 0
    assert w.new_rows() == []


def test_card_id_helper_is_valid():
    assert len(card_id(1)) == 16
