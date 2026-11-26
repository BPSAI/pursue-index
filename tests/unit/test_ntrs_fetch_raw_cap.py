"""default_get caps the raw stream and never decodes a compressed body."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from pursue_index import ntrs_fetch
from pursue_index.ntrs_fetch import NtrsFetchError, default_get

URL = "https://ntrs.nasa.gov/api/citations/search?q=x"


def _install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)

    def stream(method: str, url: str, **kw: Any) -> Any:
        kw.pop("follow_redirects", None)
        client = httpx.Client(transport=transport)
        return client.stream(method, url, **kw)

    monkeypatch.setattr(ntrs_fetch.httpx, "stream", stream)


def test_a_plain_response_under_the_cap_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda r: httpx.Response(200, json={"results": []}))
    assert default_get(URL, {}).json() == {"results": []}


def test_the_request_carries_accept_encoding_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    _install(monkeypatch, handler)
    default_get(URL, {"User-Agent": "t"})
    assert seen[0].headers["accept-encoding"] == "identity"


def test_a_gzip_encoded_response_is_refused_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = gzip.compress(json.dumps({"results": []}).encode())
    _install(
        monkeypatch,
        lambda r: httpx.Response(200, content=body, headers={"content-encoding": "gzip"}),
    )
    with pytest.raises(NtrsFetchError, match="Content-Encoding"):
        default_get(URL, {})


def test_a_raw_stream_over_the_cap_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntrs_fetch, "MAX_RESPONSE_BYTES", 100)

    def chunks() -> Iterator[bytes]:
        yield b"a" * 60
        yield b"a" * 60

    _install(monkeypatch, lambda r: httpx.Response(200, content=chunks()))
    with pytest.raises(NtrsFetchError, match="too large"):
        default_get(URL, {})
