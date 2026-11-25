"""Verify-gates round 4: the type-change warning on every lane, one 'asset gone' predicate,
the ANY_HOST contract, a credential-free refusal fingerprint, and the encoded-HEAD fetch count."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_hosts  # noqa: E402
import _r2_type_change as tc  # noqa: E402
import _r2_url  # noqa: E402
from _r2_fetch import HeadResult  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2  # noqa: E402

DRIFT_FLAGS = ("--fail-on-drift",)


def _moved_world(tmp_path, monkeypatch) -> World:
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    new_url = "https://www.war.gov/medialink/ufo/c1.mp4"
    w.cards[0].update(asset_url=new_url, asset_filename="c1.mp4", asset_type="VID")
    w.bodies[new_url] = NEW_BODY
    return w


# --- 1. the warning on every lane -----------------------------------------------------------


def test_the_poll_lane_prints_one_type_change_warning(tmp_path, monkeypatch, capsys):
    w = _moved_world(tmp_path, monkeypatch)
    assert w.run() == 0
    assert capsys.readouterr().out.count("TYPE CHANGE") == 1


def test_a_fail_on_drift_run_prints_one_type_change_warning(tmp_path, monkeypatch, capsys):
    w = _moved_world(tmp_path, monkeypatch)
    flags = [*DRIFT_FLAGS, "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    assert w.run(*flags) == 0
    assert capsys.readouterr().out.count("TYPE CHANGE") == 1


# --- 2. one 'asset gone' predicate ------------------------------------------------------------

PDF = {"asset_url": "https://h/a.pdf", "asset_filename": "a.pdf"}
CASES = [
    ("gone", [PDF], "https://h/a.mp4", "a.mp4", {"https://h/a.mp4"}, True),
    ("still present in the manifest", [PDF], "https://h/a.mp4", "a.mp4", {"https://h/a.mp4", "https://h/a.pdf"}, False),
    ("url changed, same type", [PDF], "https://h/b.pdf", "b.pdf", {"https://h/b.pdf"}, False),
    ("no previous rows", [], "https://h/a.mp4", "a.mp4", {"https://h/a.mp4"}, False),
    ("already has a row at the new url", [PDF, {"asset_url": "https://h/a.mp4", "asset_filename": "a.mp4"}],
     "https://h/a.mp4", "a.mp4", {"https://h/a.mp4"}, False),
]


@pytest.mark.parametrize(("name", "rows", "url", "fname", "current", "expect"), CASES, ids=[c[0] for c in CASES])
def test_the_asset_gone_predicate(name, rows, url, fname, current, expect):
    assert bool(tc.type_change_with_asset_gone(rows, url, fname, current)) is expect


def test_the_warning_is_not_gated_on_the_scan_window(capsys):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    old = {**PDF, "card_id": "c", "byte_sha256": "a" * 64, "fetched_at": (now - timedelta(days=30)).isoformat()}
    cards = [type("C", (), {"card_id": "c", "asset_url": "https://h/a.mp4", "asset_filename": "a.mp4"})()]
    tc.warn_type_changes({"c": [old]}, cards)
    assert capsys.readouterr().out.count("TYPE CHANGE") == 1


# --- 3. the ANY_HOST contract -----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["https://u:p@h/x", "https:///x", "https://h\\x/", "nonsense"])
def test_a_malformed_url_is_refused_even_with_any_host(bad):
    with pytest.raises(_r2_url.FetchLimitError):
        _r2_hosts.check_host(bad, _r2_hosts.ANY_HOST)
    with pytest.raises(_r2_url.FetchLimitError):
        _r2_hosts.check_resolved(bad, _r2_hosts.ANY_HOST)


def test_a_well_formed_url_to_any_host_passes_with_any_host():
    _r2_hosts.check_host("https://anything.example/a.pdf", _r2_hosts.ANY_HOST)
    assert _r2_hosts.check_resolved("https://anything.example/a.pdf", _r2_hosts.ANY_HOST) == []


# --- 4. a credential-free fingerprint ---------------------------------------------------------


def _fp(url: str) -> str:
    return str(_r2_url._refuse(url, "x")).rsplit("[", 1)[1].rstrip("]")


def test_the_fingerprint_does_not_depend_on_userinfo():
    assert _fp("https://a:x@h/p") == _fp("https://a:y@h/p") == _fp("https://h/p")
    assert _fp("https://a:x@h/p") != _fp("https://h/q")


# --- 5. encoded-HEAD fetches are counted --------------------------------------------------------


def test_a_run_with_two_encoded_assets_reports_their_fetches_and_bytes(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    for n in (1, 2):
        w.add_card(n, prior=OLD_BODY, body=NEW_BODY)
    monkeypatch.setattr(r2, "head_asset", lambda u, allowed_hosts=None: HeadResult((None, None, None), encoded=True))
    assert w.run() == 0
    assert f"encoded-head fetches: 2 (bytes {2 * len(NEW_BODY)})" in capsys.readouterr().out


def test_a_run_without_encoded_assets_reports_zero(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    w.run()
    assert "encoded-head fetches: 0 (bytes 0)" in capsys.readouterr().out
