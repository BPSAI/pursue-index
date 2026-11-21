"""fetch_asset against a real local HTTP server, with the real HTTP client.

Every other fetch test stubs the client, which is how a streamed response that
isn't a context manager reached production: the stub was one. This drives the
actual curl_cffi request path end to end.
"""

from __future__ import annotations

import hashlib
import http.server
import socketserver
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import _r2_fetch  # noqa: E402

BODY = (b"pursue-real-client-fixture-" * 40000)  # ~1 MB, several chunks


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass


@pytest.fixture()
def server():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_real_client_streams_the_body_into_the_file_and_hash(server, tmp_path):
    dest = tmp_path / "asset.pdf"
    sha, size = _r2_fetch.fetch_asset(f"{server}/asset.pdf", dest)
    assert size == len(BODY)
    assert sha == hashlib.sha256(BODY).hexdigest()
    assert dest.read_bytes() == BODY


def test_real_client_raises_on_an_http_error(server, tmp_path):
    with pytest.raises(Exception) as exc:
        _r2_fetch.fetch_asset(f"{server}/missing", tmp_path / "x.pdf")
    assert "context manager" not in str(exc.value)
