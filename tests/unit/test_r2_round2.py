"""Second-round bounds: the host allowlist is required, redirects cannot downgrade the
scheme or switch ports, a grown asset is reported (and can be allowed) as over-cap, and a
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
import _r2_run_state  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha  # noqa: E402

HOSTS = frozenset({"www.war.gov"})
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
        _r2_fetch.fetch_asset("https://evil.example/a.pdf", tmp_path / "a", allowed_hosts=None)


def test_the_explicit_any_host_sentinel_allows_any_host(monkeypatch, tmp_path):
    _serve(monkeypatch, {"https://other.example/a.pdf": _Resp(chunks=[b"ok"])})
    _, size = _r2_fetch.fetch_asset(
        "https://other.example/a.pdf", tmp_path / "a", allowed_hosts=_r2_fetch.ANY_HOST
    )
    assert size == 2


# --- 2. no scheme downgrade, no port switch --------------------------------------------


def _redirect(to):
    return _Resp(302, {"location": to})


def test_an_https_to_http_redirect_is_refused_before_it_is_requested(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("http://www.war.gov/a.pdf")})
    with pytest.raises(_r2_fetch.FetchLimitError, match="scheme"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)
    assert log == [URL]


def test_a_redirect_to_a_non_default_port_is_refused(monkeypatch, tmp_path):
    log = _serve(monkeypatch, {URL: _redirect("https://www.war.gov:8443/a.pdf")})
    with pytest.raises(_r2_fetch.FetchLimitError, match="port"):
        _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)
    assert log == [URL]


def test_a_redirect_to_an_explicit_default_port_is_followed(monkeypatch, tmp_path):
    _serve(monkeypatch, {URL: _redirect("https://www.war.gov:443/b.pdf"),
                         "https://www.war.gov:443/b.pdf": _Resp(chunks=[b"k"])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", allowed_hosts=HOSTS)[1] == 1


def test_real_client_refuses_a_redirect_to_another_local_port(tmp_path):
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
                allowed_hosts=frozenset({"127.0.0.1"}),
            )
    finally:
        for s in (target, hop):
            s.shutdown()
            s.server_close()


# --- 3. over-cap is its own reason, with an override -----------------------------------


def _grown_world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    other = w.add_card(2, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    caps: dict[str, int] = {}

    def fetch(u, dest, *, max_bytes=None, allowed_hosts=None):
        caps[str(u)] = max_bytes
        if max_bytes is not None and max_bytes < 100:
            raise _r2_fetch.FetchOverCapError(observed=4321, cap=max_bytes, declared=True)
        Path(dest).write_bytes(NEW_BODY)
        return sha(NEW_BODY), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    return w, cid, other, caps


def test_over_cap_is_reported_with_its_size_and_cap(tmp_path, monkeypatch, capsys):
    w, cid, _other, _caps = _grown_world(tmp_path, monkeypatch)
    w.run()
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if cid in ln and "over-cap" in ln)
    assert "4321" in line and str(2 * len(OLD_BODY)) in line
    assert "--allow-over-cap" in line


def test_the_override_lifts_the_cap_for_the_named_card_only(tmp_path, monkeypatch, capsys):
    w, cid, other, caps = _grown_world(tmp_path, monkeypatch)
    rc = w.run("--allow-over-cap", cid, "--reason", "publisher re-saved at higher quality")
    out = capsys.readouterr().out
    assert caps["https://www.war.gov/medialink/ufo/c1.pdf"] == _r2_fetch.MAX_ASSET_BYTES
    assert caps["https://www.war.gov/medialink/ufo/c2.pdf"] == 2 * len(OLD_BODY)
    assert [r["card_id"] for r in w.new_rows()] == [cid]
    assert cid in out and "publisher re-saved at higher quality" in out
    assert any("over-cap" in ln and other in ln for ln in out.splitlines())
    assert rc == 0


def test_the_override_takes_a_comma_separated_list(tmp_path, monkeypatch):
    w, cid, other, caps = _grown_world(tmp_path, monkeypatch)
    w.run("--allow-over-cap", f"{cid},{other}", "--reason", "both re-saved")
    assert set(caps.values()) == {_r2_fetch.MAX_ASSET_BYTES}


def test_the_override_needs_a_reason(tmp_path, monkeypatch, capsys):
    w, cid, _o, _c = _grown_world(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        w.run("--allow-over-cap", cid)
    assert "--reason" in capsys.readouterr().err


def test_the_override_never_lifts_the_absolute_ceiling():
    huge = [{"byte_size": _r2_fetch.MAX_ASSET_BYTES}]
    assert _r2_fetch.byte_cap(huge, lifted=True) == _r2_fetch.MAX_ASSET_BYTES
    assert _r2_fetch.byte_cap([{"byte_size": 10}], lifted=True) == _r2_fetch.MAX_ASSET_BYTES


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
