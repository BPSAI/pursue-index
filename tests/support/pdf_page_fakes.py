"""Fixture PDFs and a fake ``http_get`` for the poll lane's page counter.

Shared by the unit tests of ``pursue_index.scrape.pdf_pages`` and the
end-to-end ``scripts/poll_snapshot.py`` test (which installs the same fake in
a subprocess via ``sitecustomize``), so neither touches the network.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfWriter


def pdf_bytes(pages: int) -> bytes:
    """A valid PDF with ``pages`` blank pages."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@dataclass
class FakeResponse:
    """A response that also streams, like ``curl_cffi``'s ``stream=True``.

    ``consumed`` records how many body bytes a caller actually pulled, so a
    test can tell a capped read from a full download.
    """

    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    consumed: int = 0
    closed: bool = False

    def iter_content(self, chunk_size: int | None = None) -> Iterator[bytes]:
        step = chunk_size or 1024
        for start in range(0, len(self.content), step):
            chunk = self.content[start:start + step]
            self.consumed += len(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeHttpGet:
    """Serves ``bodies[url]``; a URL in ``fail`` raises, one absent 404s.

    A URL in ``redirects`` answers 302 with that ``Location``.
    """

    bodies: Mapping[str, bytes]
    fail: frozenset[str] = frozenset()
    redirects: Mapping[str, str] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    responses: list[FakeResponse] = field(default_factory=list)

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if url in self.fail:
            raise ConnectionError(f"simulated transport failure for {url}")
        if url in self.redirects:
            resp = FakeResponse(302, b"", {"Location": self.redirects[url]})
        elif url not in self.bodies:
            resp = FakeResponse(status_code=404, content=b"")
        else:
            body = self.bodies[url]
            resp = FakeResponse(200, body, {"Content-Length": str(len(body))})
        self.responses.append(resp)
        return resp
