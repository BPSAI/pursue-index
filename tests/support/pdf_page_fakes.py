"""Fixture PDFs and a fake ``http_get`` for the poll lane's page counter.

Shared by the unit tests of ``pursue_index.scrape.pdf_pages`` and the
end-to-end ``scripts/poll_snapshot.py`` test (which installs the same fake in
a subprocess via ``sitecustomize``), so neither touches the network.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
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
    status_code: int
    content: bytes


@dataclass
class FakeHttpGet:
    """Serves ``bodies[url]``; a URL in ``fail`` raises, one absent 404s."""

    bodies: Mapping[str, bytes]
    fail: frozenset[str] = frozenset()
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if url in self.fail:
            raise ConnectionError(f"simulated transport failure for {url}")
        if url not in self.bodies:
            return FakeResponse(status_code=404, content=b"")
        return FakeResponse(status_code=200, content=self.bodies[url])
