"""Third-round behaviour: approved CDN hosts are followed (and logged), and a grown asset is
an alert, not a failed card, until it passes the absolute ceiling."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402

from tests.unit.r2_verify_harness import OLD_BODY, World, r2, sha  # noqa: E402

pytestmark = pytest.mark.usefixtures("dns")

URL = "https://www.war.gov/a.pdf"
CDN = "https://cdn.example.com/a.pdf"
APPROVED = _SCRIPTS.parent / "data" / "approved-asset-hosts.json"


class _Resp:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code, self.headers, self._chunks = status, headers or {}, list(chunks)

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int = 0):
        yield from self._chunks

    def close(self) -> None: ...


def _serve(monkeypatch, routes):
    log = []

    def fake_get(url, **kw):
        log.append(url)
        return routes[url]

    monkeypatch.setattr(_r2_fetch.cffi_requests, "get", fake_get)
    return log


# --- 1. approved hosts ------------------------------------------------------------------


def test_the_committed_list_holds_the_manifest_host_and_a_comment():
    got = json.loads(APPROVED.read_text())
    assert got["hosts"] == ["www.war.gov"] and got["comment"].strip()
    assert _r2_hosts.load_approved_hosts(APPROVED) == frozenset({"www.war.gov"})


def _approved(tmp_path, body) -> Path:
    path = tmp_path / "approved.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def test_a_well_formed_list_is_lower_cased_and_read(tmp_path):
    path = _approved(tmp_path, {"comment": "c", "hosts": ["CDN.Example.com"]})
    assert _r2_hosts.load_approved_hosts(path) == frozenset({"cdn.example.com"})


@pytest.mark.parametrize(
    "body",
    ["not json", "[]", {"hosts": "cdn.example.com"}, {"hosts": [1]}, {"hosts": [""]}, {"comment": "x"}],
)
def test_a_malformed_list_fails_closed(tmp_path, body):
    with pytest.raises(_r2_hosts.ApprovedHostsError):
        _r2_hosts.load_approved_hosts(_approved(tmp_path, body))


def test_a_missing_list_fails_closed(tmp_path):
    with pytest.raises(_r2_hosts.ApprovedHostsError):
        _r2_hosts.load_approved_hosts(tmp_path / "nope.json")


def test_main_stops_on_a_malformed_list_before_any_fetch(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, head_matches_prior=False)
    bad = _approved(tmp_path, "not json")
    assert w.run("--approved-hosts", str(bad)) == 1
    assert w.fetched == [] and "approved" in capsys.readouterr().err


def _hosts_seen_by_fetch(tmp_path, monkeypatch, *extra):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    seen = {}

    def fetch(u, dest, **kw):
        seen.update(kw)
        Path(dest).write_bytes(OLD_BODY)
        return sha(OLD_BODY), len(OLD_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run(*extra)
    return seen["allowed_hosts"]


def test_main_adds_the_approved_hosts_to_the_manifest_hosts(tmp_path, monkeypatch):
    path = _approved(tmp_path, {"comment": "c", "hosts": ["www.war.gov", "cdn.example.com"]})
    got = _hosts_seen_by_fetch(tmp_path, monkeypatch, "--approved-hosts", str(path))
    assert got == frozenset({"www.war.gov", "cdn.example.com"})


def test_main_without_extra_hosts_allows_only_the_manifest_host(tmp_path, monkeypatch):
    assert _hosts_seen_by_fetch(tmp_path, monkeypatch) == frozenset({"www.war.gov"})


def test_an_approved_cross_host_hop_is_followed(monkeypatch, tmp_path):
    _serve(monkeypatch, {URL: _Resp(302, {"location": CDN}), CDN: _Resp(chunks=[b"ok"])})
    hosts = frozenset({"www.war.gov", "cdn.example.com"})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=hosts)[1] == 2


def test_an_unapproved_cross_host_hop_is_refused_before_it_is_requested(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _Resp(302, {"location": CDN})})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"cdn\.example\.com"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=frozenset({"www.war.gov"}))
    assert log == [URL]


def test_every_hop_is_logged_with_hosts_only(monkeypatch, tmp_path, capsys):
    secret = "https://cdn.example.com/a.pdf?token=SECRET"
    _serve(monkeypatch, {URL: _Resp(301, {"location": secret}), secret: _Resp(chunks=[b"ok"])})
    hosts = frozenset({"www.war.gov", "cdn.example.com"})
    with _r2_fetch.for_card("00000000000000aa"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=hosts)
    out = capsys.readouterr().out
    assert "[r2-archive] redirect: 00000000000000aa www.war.gov -> cdn.example.com (301)" in out
    assert "SECRET" not in out and "/a.pdf" not in out


# --- 2. growth past the 2x cap is an alert --------------------------------------------

GROWN = b"g" * (3 * len(OLD_BODY))


def _grown(tmp_path, monkeypatch, body=GROWN):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=body, head_matches_prior=False)
    return w, cid


FULL = ("--full-hash", "--max-bytes-per-run", "100000")


def test_growth_past_the_cap_alerts_and_the_card_is_archived(tmp_path, monkeypatch, capsys):
    w, cid = _grown(tmp_path, monkeypatch)
    rc = w.run(*FULL, "--run-record", str(w.record))
    out = capsys.readouterr()
    assert (
        f"[r2-archive] SIZE ALERT: {cid} {len(OLD_BODY)} -> {len(GROWN)} (over the 2x growth cap)"
        in out.out
    )
    assert "size_alerts=1" in out.out and "fail=0" in out.out
    assert [r["byte_sha256"] for r in w.new_rows()] == [sha(GROWN)]
    assert rc == 0 and w.record.exists(), "the weekly run stays complete"


def test_growth_with_unchanged_bytes_logic_still_applies(tmp_path, monkeypatch, capsys):
    """The normal outcome is decided by the bytes: here a new sha, so drift is still caught."""
    w, _cid = _grown(tmp_path, monkeypatch)
    rc = w.run(*FULL, "--run-record", str(w.record), "--fail-on-drift")
    assert rc == 1 and "BYTE DRIFT" in capsys.readouterr().err


def test_growth_within_the_cap_does_not_alert(tmp_path, monkeypatch, capsys):
    w, _ = _grown(tmp_path, monkeypatch, body=b"n" * (2 * len(OLD_BODY)))
    w.run()
    out = capsys.readouterr().out
    assert "SIZE ALERT" not in out and "size_alerts=0" in out


def test_the_summary_counts_every_alert(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    for n in (1, 2):
        w.add_card(n, prior=OLD_BODY, body=GROWN, head_matches_prior=False)
    w.run()
    assert "size_alerts=2" in capsys.readouterr().out


def test_growth_past_the_hard_ceiling_still_fails_the_card(tmp_path, monkeypatch, capsys):
    w, _cid = _grown(tmp_path, monkeypatch)

    def fetch(u, dest, **kw):
        raise _r2_fetch.FetchOverCapError(
            observed=_r2_fetch.MAX_ASSET_BYTES + 1, cap=_r2_fetch.MAX_ASSET_BYTES, declared=True
        )

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    rc = w.run(*FULL, "--run-record", str(w.record))
    out = capsys.readouterr()
    assert "fail=1" in out.out and "size_alerts=0" in out.out
    assert rc == 1 and not w.record.exists() and w.new_rows() == []


def test_the_allow_over_cap_flag_is_gone(tmp_path, monkeypatch, capsys):
    w, cid = _grown(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        w.run("--allow-over-cap", cid, "--reason", "x")
    assert "--allow-over-cap" in capsys.readouterr().err
