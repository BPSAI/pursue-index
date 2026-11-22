"""Verify-gates round 2: the host list comes from the committed file, and every request resolves."""

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
from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _redirect, _Resp, _serve  # noqa: E402

# --- 3. allowlist from the committed file; resolved addresses ---------------------------


def _approved(tmp_path, hosts):
    p = tmp_path / "approved.json"
    p.write_text(json.dumps({"comment": "c", "hosts": hosts}))
    return p


def test_main_allows_only_the_committed_approved_hosts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    seen: dict = {}

    def fetch(u, dest, **kw):
        seen.update(kw)
        Path(dest).write_bytes(OLD_BODY)
        return sha(OLD_BODY), len(OLD_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    path = _approved(tmp_path, ["www.war.gov", "cdn.example.com"])
    assert w.run("--approved-hosts", str(path)) == 0
    assert seen["allowed_hosts"] == frozenset({"www.war.gov", "cdn.example.com"})


def test_a_manifest_host_missing_from_the_approved_list_stops_the_run(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    w.cards[0]["asset_url"] = "https://rogue.example.org/x.pdf"
    w.bodies["https://rogue.example.org/x.pdf"] = OLD_BODY
    assert w.run("--approved-hosts", str(_approved(tmp_path, ["www.war.gov"]))) == 1
    err = capsys.readouterr().err
    assert "rogue.example.org" in err and "approved" in err
    assert w.fetched == [] and w.headed == []


def test_the_default_approved_list_covers_the_committed_manifest():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "data" / "manifests" / "latest.json").read_text())
    approved = _r2_hosts.load_approved_hosts(root / "data" / "approved-asset-hosts.json")
    hosts = _r2_hosts.allowed_hosts_from_urls(c.get("asset_url") for c in manifest["cards"])
    assert hosts <= approved


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "::"],
)
def test_a_host_resolving_to_a_non_public_address_is_refused(monkeypatch, tmp_path, dns, ip):
    dns["www.war.gov"] = ip
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"www\.war\.gov"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_one_private_answer_among_public_ones_refuses_the_host(monkeypatch, tmp_path):
    import socket

    def mixed(host, port=None, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)


def test_resolution_failure_refuses_the_request(monkeypatch, tmp_path):
    import socket

    def boom(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="resolve"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_every_hop_is_resolved_before_it_is_requested(monkeypatch, tmp_path, dns):
    dns["cdn.example.com"] = "10.1.2.3"
    log = _serve(monkeypatch, {URL: _redirect("https://cdn.example.com/a.pdf")})
    hosts = frozenset({"www.war.gov", "cdn.example.com"})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"cdn\.example\.com"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=hosts)
    assert [u for u, _ in log] == [URL]


def test_head_refuses_a_host_that_resolves_to_loopback(monkeypatch, dns):
    dns["www.war.gov"] = "127.0.0.1"
    calls: list[str] = []
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: calls.append(u))
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS) == (None, None, None)
    assert calls == []
