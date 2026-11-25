"""Review round 2: only globally routable addresses, and the request goes to the address that passed."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402
from curl_cffi import requests as cffi_requests  # noqa: E402

from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _redirect, _Resp, _serve  # noqa: E402
from tests.unit.test_r2_fetch_gates_round2 import _Local, local  # noqa: E402,F401

PUBLIC = "93.184.216.34"
RESOLVE = 10203  # CURLOPT_RESOLVE


# --- global addresses only ------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "100.64.0.1", "100.127.255.254",  # CGNAT 100.64.0.0/10
        "64:ff9b::808:808", "64:ff9b::7f00:1",  # NAT64 64:ff9b::/96
        "192.0.0.8", "198.18.0.1", "198.51.100.7", "203.0.113.9", "192.0.2.1", "240.0.0.1",
        "255.255.255.255", "2001:db8::1", "2002:7f00:1::", "fc00::1", "::ffff:127.0.0.1",
        "::ffff:100.64.0.1",
    ],
)
def test_reserved_and_translation_ranges_are_refused(monkeypatch, tmp_path, dns, ip):
    dns["www.war.gov"] = ip
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"non-public"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


@pytest.mark.parametrize("ip", [PUBLIC, "8.8.8.8", "2606:4700:4700::1111", "100.63.255.255"])
def test_global_addresses_are_allowed(monkeypatch, tmp_path, dns, ip):
    dns["www.war.gov"] = ip
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)[1] == 1


# --- pinning the checked address -------------------------------------------------------------


def _rebinding(monkeypatch, first: str, then: str) -> list[str]:
    """A resolver that answers ``first`` once, then ``then``; returns the log of lookups."""
    answers = [first]
    lookups: list[str] = []

    def getaddrinfo(host, port=None, *a, **k):
        lookups.append(str(host))
        ip = answers.pop(0) if answers else then
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return lookups


def test_the_request_is_pinned_to_the_address_that_passed_the_check(monkeypatch, tmp_path):
    _rebinding(monkeypatch, PUBLIC, "127.0.0.1")
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    opts = log[0][1]["curl_options"]
    assert opts[RESOLVE] == [f"www.war.gov:443:{PUBLIC}"]
    assert 19 in opts and 20 in opts, "the idle-timeout options are kept"


def test_the_pin_option_is_curls_resolve_option():
    from curl_cffi.const import CurlOpt

    assert _r2_fetch._CURLOPT_RESOLVE == CurlOpt.RESOLVE == RESOLVE


def test_every_redirect_hop_is_pinned_to_its_own_checked_address(monkeypatch, tmp_path, dns):
    dns["cdn.example.com"] = "93.184.216.99"
    other = "https://cdn.example.com/a.pdf"
    log = _serve(monkeypatch, {URL: _redirect(other), other: _Resp(chunks=[b"x"])})
    hosts = frozenset({"www.war.gov", "cdn.example.com"})
    _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=hosts)
    assert [kw["curl_options"][RESOLVE] for _, kw in log] == [
        [f"www.war.gov:443:{PUBLIC}"],
        ["cdn.example.com:443:93.184.216.99"],
    ]


def test_head_is_pinned_too(monkeypatch):
    _rebinding(monkeypatch, PUBLIC, "127.0.0.1")
    seen: list[dict] = []

    def head(url, **kw):
        seen.append(kw)
        return _Resp(headers={"content-length": "3"})

    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", head)
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS)[0] == 3
    assert seen[0]["curl_options"][RESOLVE] == [f"www.war.gov:443:{PUBLIC}"]


def test_an_ipv6_address_is_pinned_in_brackets(monkeypatch, tmp_path, dns):
    dns["www.war.gov"] = "2606:4700:4700::1111"
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log[0][1]["curl_options"][RESOLVE] == ["www.war.gov:443:[2606:4700:4700::1111]"]


def test_all_checked_answers_are_pinned_in_order(monkeypatch, tmp_path):
    def two(host, port=None, *a, **k):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", two)
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log[0][1]["curl_options"][RESOLVE] == [f"www.war.gov:443:{PUBLIC},8.8.8.8"]


def test_no_pin_when_the_check_is_opted_out(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=_r2_hosts.ANY_HOST)
    assert RESOLVE not in log[0][1]["curl_options"]


def test_real_curl_connects_to_the_pinned_address_not_the_name(local):  # noqa: F811
    """curl_cffi accepts ``{CURLOPT_RESOLVE: ["host:port:addr"]}``: a name that resolves nowhere
    still reaches the local server, so the pin is what decided the destination."""
    port = int(local.rsplit(":", 1)[1])
    resp = cffi_requests.get(
        f"http://pinned.invalid:{port}/a.pdf",
        timeout=10,
        curl_options={RESOLVE: [f"pinned.invalid:{port}:127.0.0.1"]},
    )
    assert resp.status_code == 200 and resp.content == _Local.body
