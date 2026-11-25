"""Verify-gates round 3: one strict URL parse, used by every check and by the request itself."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402

from tests.unit.test_r2_fetch_bounds import HOSTS, _redirect, _Resp, _serve  # noqa: E402

REFUSED = [
    "https://evil@good/",
    "https://www.war.gov@evil.com/a.pdf",
    "https://user:pw@www.war.gov/a.pdf",
    "https://good\\@evil/",
    "https://www.war.gov\\.evil.com/a.pdf",
    "https://www.war.gov/a\\b.pdf",
    "https://good%2f@evil/",
    "https://www.war.gov%2f.evil.com/a.pdf",
    "https://www.wär.gov/a.pdf",
    "https://www.war.gov/ä.pdf".replace("/ä", "/\\ä"),
    "https://www.war.gov:0/a.pdf",
    "https://www.war.gov:99999/a.pdf",
    "https://www.war.gov:65536/a.pdf",
    "https://www.war.gov:/a.pdf",
    "https://www.war.gov:abc/a.pdf",
    "https://www.war.gov:-1/a.pdf",
    "https:///a.pdf",
    "https://:443/a.pdf",
    "https://www.war.gov../a.pdf",
    "https://.www.war.gov/a.pdf",
    "https://www..war.gov/a.pdf",
    "https://www.war.gov /a.pdf",
    "https://www.war.gov\t/a.pdf",
    "https://www.war.gov\n/a.pdf",
    "https://[::1]/a.pdf",
    "https://2130706433/a.pdf",
    "https://0x7f.1/a.pdf",
    "https://127.1/a.pdf",
    "https://127.000.000.1/a.pdf",
    "www.war.gov/a.pdf",
    "https:www.war.gov/a.pdf",
]


@pytest.mark.parametrize("bad", REFUSED)
def test_strict_parse_refuses(bad):
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_hosts.parse_url(bad)


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("https://www.war.gov/a.pdf", "www.war.gov", 443),
        ("https://WWW.War.GOV/a.pdf", "www.war.gov", 443),
        ("https://www.war.gov./a.pdf", "www.war.gov", 443),
        ("https://www.war.gov:8443/a.pdf", "www.war.gov", 8443),
        ("https://www.war.gov:1/a.pdf", "www.war.gov", 1),
        ("https://www.war.gov:65535", "www.war.gov", 65535),
        ("https://xn--bcher-kva.example/x", "xn--bcher-kva.example", 443),
        ("https://127.0.0.1/a", "127.0.0.1", 443),
        ("https://www.war.gov/a.pdf?q=a@b#f", "www.war.gov", 443),
    ],
)
def test_strict_parse_returns_the_exact_normalized_host(url, host, port):
    parsed = _r2_hosts.parse_url(url)
    assert (parsed.host, parsed.port) == (host, port)


def test_the_canonical_url_keeps_the_path_and_query_and_names_the_normalized_host():
    parsed = _r2_hosts.parse_url("https://WWW.War.GOV.:8443/a%20b.pdf?q=1")
    assert parsed.url == "https://www.war.gov:8443/a%20b.pdf?q=1"


@pytest.mark.parametrize("bad", REFUSED)
def test_check_host_and_resolution_refuse_what_the_parse_refuses(bad, dns):
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_hosts.check_host(bad, HOSTS | {"good", "evil"})
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_hosts.check_resolved(bad, HOSTS | {"good", "evil"})


def test_an_allowed_host_in_userinfo_does_not_pass_the_allowlist(monkeypatch, tmp_path, dns):
    bad = "https://www.war.gov@evil.example/a.pdf"
    log = _serve(monkeypatch, {bad: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_hosts.FetchLimitError):
        _r2_fetch.fetch_asset(bad, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_a_redirect_with_userinfo_or_a_backslash_is_refused(monkeypatch, tmp_path, dns):
    url = "https://www.war.gov/a.pdf"
    for target in ("https://www.war.gov\\@evil.example/x", "https://evil@www.war.gov/x"):
        log = _serve(monkeypatch, {url: _redirect(target)})
        with pytest.raises(_r2_hosts.FetchLimitError):
            _r2_fetch.fetch_asset(url, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
        assert [u for u, _ in log] == [url]


def test_the_request_uses_the_normalized_url_and_the_pin_names_the_same_host(monkeypatch, tmp_path, dns):
    sent = _serve(monkeypatch, {"https://www.war.gov:8443/a.pdf": _Resp(chunks=[b"x"])})
    dns["www.war.gov"] = "93.184.216.34"
    _r2_fetch.fetch_asset(
        "https://WWW.War.GOV.:8443/a.pdf", tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS
    )
    (url, kw), = sent
    assert url == "https://www.war.gov:8443/a.pdf"
    assert kw["curl_options"][_r2_hosts.CURLOPT_RESOLVE] == ["www.war.gov:8443:93.184.216.34"]
