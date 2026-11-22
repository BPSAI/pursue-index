"""Second-round bounds: the host allowlist is required, redirects cannot downgrade the
scheme or switch ports, a body past the cap raises the over-cap error, and a
weekly record with no start falls back to the bootstrap window."""

from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402
import _r2_hosts  # noqa: E402
import _r2_run_state  # noqa: E402

HOSTS = frozenset({"www.war.gov"})
pytestmark = pytest.mark.usefixtures("dns")

URL = "https://www.war.gov/a.pdf"


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


# --- 1. the allowlist is required -----------------------------------------------------


def test_fetch_without_hosts_is_a_type_error(tmp_path, monkeypatch):
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(TypeError):
        _r2_fetch.fetch_asset(URL, tmp_path / "a")  # type: ignore[call-arg]


def test_head_without_hosts_is_a_type_error(monkeypatch):
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda *a, **k: _Resp())
    with pytest.raises(TypeError):
        _r2_fetch.head_asset(URL)  # type: ignore[call-arg]


def test_none_is_not_a_way_to_skip_the_check(monkeypatch, tmp_path):
    _serve(monkeypatch, {"https://evil.example/a.pdf": _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.FetchLimitError):
        _r2_fetch.fetch_asset("https://evil.example/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=None)


def test_the_explicit_any_host_sentinel_allows_any_host(monkeypatch, tmp_path):
    _serve(monkeypatch, {"https://other.example/a.pdf": _Resp(chunks=[b"ok"])})
    _, size = _r2_fetch.fetch_asset(
        "https://other.example/a.pdf", tmp_path / "a", max_bytes=10**6, allowed_hosts=_r2_fetch.ANY_HOST
    )
    assert size == 2


# --- 2. no scheme downgrade, no port switch --------------------------------------------


def _redirect(to):
    return _Resp(302, {"location": to})


def test_an_https_to_http_redirect_is_refused_before_it_is_requested(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("http://www.war.gov/a.pdf")})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=HOSTS)
    assert log == [URL]


def test_a_redirect_to_a_non_default_port_is_refused(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("https://www.war.gov:8443/a.pdf")})
    with pytest.raises(_r2_fetch.FetchLimitError, match="port"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=HOSTS)
    assert log == [URL]


def test_a_redirect_to_an_explicit_default_port_is_followed(monkeypatch, tmp_path):
    _serve(monkeypatch, {URL: _redirect("https://www.war.gov:443/b.pdf"),
                         "https://www.war.gov:443/b.pdf": _Resp(chunks=[b"k"])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=10**6, allowed_hosts=HOSTS)[1] == 1


@pytest.fixture()
def _local_seam():
    with _r2_hosts.allow_local_for_tests():
        yield


def test_real_client_refuses_a_redirect_to_another_local_port(tmp_path, monkeypatch, _local_seam):
    class _Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a): ...

    target = socketserver.TCPServer(("127.0.0.1", 0), _Target)
    port = target.server_address[1]

    class _Hop(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/x")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a): ...

    hop = socketserver.TCPServer(("127.0.0.1", 0), _Hop)
    for s in (target, hop):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with pytest.raises(_r2_fetch.FetchLimitError, match="port"):
            _r2_fetch.fetch_asset(
                f"http://127.0.0.1:{hop.server_address[1]}/a",
                tmp_path / "a",
                max_bytes=10**6,
                allowed_hosts=frozenset({"127.0.0.1"}),
            )
    finally:
        for s in (target, hop):
            s.shutdown()
            s.server_close()


# --- 3. a streamed body past the cap raises the over-cap error ---------------------------


def test_a_streamed_body_past_the_cap_raises_the_over_cap_error(monkeypatch, tmp_path):
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 10, b"y" * 10])})
    with pytest.raises(_r2_fetch.FetchOverCapError) as exc:
        _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=15, allowed_hosts=HOSTS)
    assert "20" in str(exc.value) and "15" in str(exc.value)


# --- 4. a missing started_at falls back to the bootstrap window ------------------------


def test_a_run_with_no_recorded_start_writes_the_bootstrap_window(tmp_path):
    record = tmp_path / "runs.jsonl"
    args = SimpleNamespace(
        dry_run=False, run_record=record, registry=tmp_path / "reg.jsonl",
        max_bytes_per_run=10, full_hash=True,
    )
    state = _r2_run_state.RunState(full_hash=True)  # started_at left empty
    assert _r2_run_state.full_hash_outcome(args, state) == 0
    row = json.loads(record.read_text())
    started = datetime.fromisoformat(row["started_at"])
    done = datetime.fromisoformat(row["completed_at"])
    window = timedelta(days=_r2_run_state.BOOTSTRAP_WINDOW_DAYS)
    assert abs((done - started) - window) < timedelta(seconds=5)
    assert datetime.now(UTC) - started >= window - timedelta(seconds=5)
