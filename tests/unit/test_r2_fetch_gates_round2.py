"""Verify-gates round 2, fetch side: disk headroom, https only, resolved addresses, the host
list, ceilings and encoded bodies."""

from __future__ import annotations

import gzip
import hashlib
import http.server
import socketserver
import sys
import threading
from collections import namedtuple
from pathlib import Path
from typing import ClassVar

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha  # noqa: E402
from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _redirect, _Resp, _serve  # noqa: E402

MIB = 1024**2
Usage = namedtuple("Usage", "total used free")


# --- 1. disk exhaustion ---------------------------------------------------------------


def test_max_bytes_is_a_required_argument(tmp_path):
    with pytest.raises(TypeError, match="max_bytes"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)  # type: ignore[call-arg]


def test_low_disk_is_refused_before_any_byte_is_read(monkeypatch, tmp_path, dns):
    resp = _Resp(chunks=[b"x"])
    log = _serve(monkeypatch, {URL: resp})
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**12, 10**12, 1000))
    with pytest.raises(_r2_fetch.FetchLimitError, match="insufficient disk"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=1000, allowed_hosts=HOSTS)
    assert log == [] and resp.yielded == 0
    assert not (tmp_path / "a").exists()


def test_the_disk_check_needs_the_ceiling_plus_the_margin(monkeypatch, tmp_path, dns):
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    need = 1000 + _r2_fetch.DISK_MARGIN_BYTES
    seen = []

    def usage(path):
        seen.append(Path(path))
        return Usage(10**12, 0, need)

    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", usage)
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=1000, allowed_hosts=HOSTS)[1] == 1
    assert seen == [tmp_path]
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**12, 0, need - 1))
    with pytest.raises(_r2_fetch.FetchLimitError, match="insufficient disk"):
        _r2_fetch.fetch_asset(URL, tmp_path / "b", max_bytes=1000, allowed_hosts=HOSTS)


def test_low_disk_is_one_cards_failure_naming_the_disk(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, body=NEW_BODY)

    def fetch(u, dest, **kw):
        raise _r2_fetch.InsufficientDiskError(need=5, free=1)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    out = capsys.readouterr().out
    assert f"fetch fail {cid}" in out and "insufficient disk" in out and "fail=1" in out


def test_the_run_budget_caps_the_ceiling(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=OLD_BODY)
    w.add_card(2, body=NEW_BODY)
    seen: list[int] = []

    def fetch(u, dest, **kw):
        seen.append(kw["max_bytes"])
        body = w.bodies[str(u)]
        Path(dest).write_bytes(body)
        return sha(body), len(body)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    assert w.run("--full-hash", "--max-bytes-per-run", "1000", "--run-record", str(w.record)) == 0
    assert seen == [1000, 1000 - len(OLD_BODY)]


def test_without_a_run_budget_the_ceiling_is_the_assets_own(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=NEW_BODY)
    seen: list[int] = []

    def fetch(u, dest, **kw):
        seen.append(kw["max_bytes"])
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    assert seen == [_r2_fetch.MAX_ASSET_BYTES]


def test_an_asset_that_outgrows_the_budget_left_fails_the_run_as_over_budget(
    tmp_path, monkeypatch, capsys
):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, body=NEW_BODY)

    def fetch(u, dest, **kw):
        raise _r2_fetch.FetchOverCapError(observed=kw["max_bytes"] + 1, cap=kw["max_bytes"], declared=True)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    assert w.run("--full-hash", "--max-bytes-per-run", "5", "--run-record", str(w.record)) == 1
    assert "byte budget" in capsys.readouterr().err and not w.record.exists()


# --- 2. scheme enforcement ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["http://www.war.gov/a.pdf", "ftp://www.war.gov/a.pdf", "file://www.war.gov/etc/passwd",
            "gopher://www.war.gov/a", "//www.war.gov/a.pdf"],
)
def test_the_initial_url_must_be_https(monkeypatch, tmp_path, dns, bad):
    log = _serve(monkeypatch, {bad: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(bad, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log == []


def test_head_refuses_a_non_https_initial_url(monkeypatch, dns):
    calls: list[str] = []
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: calls.append(u))
    assert _r2_fetch.head_asset("http://www.war.gov/a.pdf", allowed_hosts=HOSTS) == (None, None, None)
    assert calls == []


@pytest.mark.parametrize("target", ["http://www.war.gov/a.pdf", "ftp://www.war.gov/a", "file:///etc/passwd"])
def test_a_downgrade_or_other_scheme_hop_is_refused(monkeypatch, tmp_path, dns, target):
    log = _serve(monkeypatch, {URL: _redirect(target)})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10, allowed_hosts=HOSTS)
    assert log and [u for u, _ in log] == [URL]


def test_an_http_to_https_upgrade_hop_is_allowed_and_logged(capsys):
    _r2_hosts.check_hop("http://www.war.gov/a.pdf", "https://www.war.gov/a.pdf")
    _r2_hosts.log_hop("http://www.war.gov/a.pdf", "https://www.war.gov/a.pdf", 301)
    out = capsys.readouterr().out
    assert "scheme upgrade" in out and "http -> https" in out and "www.war.gov" in out


def test_http_to_other_scheme_hop_is_refused():
    for target in ("ftp://www.war.gov/a", "gopher://www.war.gov/a"):
        with pytest.raises(_r2_hosts.FetchLimitError, match="scheme"):
            _r2_hosts.check_hop("http://www.war.gov/a.pdf", target)


# the real client, against a local server (explicit test-only seam for http + loopback)


class _Local(http.server.BaseHTTPRequestHandler):
    hits: ClassVar[list[str]] = []
    body = b"pursue-real-client-" * 4000

    def do_GET(self) -> None:
        type(self).hits.append(self.path)
        if self.path == "/gz":
            data = gzip.compress(type(self).body)
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture()
def local():
    _Local.hits = []
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Local)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


LOCAL = frozenset({"127.0.0.1"})


def test_real_client_never_requests_an_http_url_without_the_test_seam(local, tmp_path):
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(f"{local}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL)
    assert _Local.hits == []


def test_real_client_refuses_loopback_without_the_test_seam(local, tmp_path, monkeypatch):
    # https URL to a loopback literal: refused on the resolved address, nothing is sent.
    port = local.rsplit(":", 1)[1]
    with pytest.raises(_r2_fetch.FetchLimitError, match=r"private|loopback|address"):
        _r2_fetch.fetch_asset(
            f"https://127.0.0.1:{port}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL
        )
    assert _Local.hits == []


# --- 4. ceilings -----------------------------------------------------------------------


def test_the_ceiling_is_the_higher_of_the_configured_and_the_measured_one():
    ceiling = _r2_fetch.hard_ceiling
    assert ceiling([{"byte_size": 1000}]) == _r2_fetch.MAX_ASSET_BYTES
    assert ceiling([{"byte_size": 10 * MIB}]) == _r2_fetch.MAX_ASSET_BYTES
    assert ceiling([{"byte_size": 150 * MIB}]) == _r2_fetch.MAX_ASSET_BYTES
    assert ceiling([{"byte_size": 400 * MIB}]) == 4000 * MIB
    assert ceiling([{"byte_size": 3_212_900_000}]) == 32_129_000_000
    assert ceiling([]) == _r2_fetch.MAX_ASSET_BYTES
    assert ceiling([{"byte_size": None}]) == _r2_fetch.MAX_ASSET_BYTES


def test_the_growth_alert_stays_at_twice_the_known_size():
    assert _r2_fetch.byte_cap([{"byte_size": 1000}]) == 2000


# --- 6. Content-Length against encoded bodies --------------------------------------------


def test_an_encoded_response_is_not_refused_on_its_compressed_length(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "100", "content-encoding": "gzip"}, chunks=[b"x" * 40])
    _serve(monkeypatch, {URL: resp})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)[1] == 40


def test_an_encoded_body_is_still_capped_on_its_decoded_bytes(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "10", "content-encoding": "br"}, chunks=[b"x" * 40, b"y" * 40])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchOverCapError) as exc:
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)
    assert not exc.value.declared


def test_an_identity_response_keeps_the_declared_length_check(monkeypatch, tmp_path, dns):
    resp = _Resp(headers={"content-length": "100", "content-encoding": "identity"}, chunks=[b"x"])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.FetchOverCapError) as exc:
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=50, allowed_hosts=HOSTS)
    assert exc.value.declared and resp.yielded == 0


def test_head_does_not_report_a_compressed_length_as_the_size(monkeypatch, dns):
    resp = _Resp(headers={"content-length": "7", "content-encoding": "gzip", "etag": '"e"'})
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: resp)
    assert _r2_fetch.head_asset(URL, allowed_hosts=HOSTS) == (None, '"e"', None)


@pytest.fixture()
def seam():
    with _r2_hosts.allow_local_for_tests():
        yield


def test_real_client_hashes_the_decoded_bytes_and_caps_them_as_decoded(local, seam, tmp_path):
    body = _Local.body
    dest = tmp_path / "a"
    sha_, size = _r2_fetch.fetch_asset(f"{local}/gz", dest, max_bytes=len(body), allowed_hosts=LOCAL)
    assert (sha_, size) == (hashlib.sha256(body).hexdigest(), len(body))
    assert dest.read_bytes() == body
    assert len(gzip.compress(body)) < len(body) // 4, "the declared length is the compressed one"
    with pytest.raises(_r2_fetch.FetchOverCapError):
        _r2_fetch.fetch_asset(f"{local}/gz", tmp_path / "b", max_bytes=len(body) - 1, allowed_hosts=LOCAL)


def test_real_client_fetches_loopback_http_through_the_test_seam(local, seam, tmp_path):
    assert _r2_fetch.fetch_asset(
        f"{local}/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=LOCAL
    )[1] == len(_Local.body)


