"""Independent cross-check for a ``metadata-only`` verdict.

Deliberately does NOT import ``pdf_update``: it uses only pypdf's own object
model. For both files it hashes each page's raw content-stream bytes (every
stream of a page, in order, with its filter entries) and extracts each page's
text, then requires page-for-page equality. Raw (still-encoded) bytes are
hashed so no content stream is ever inflated just to be compared; the text
signal is the second, decode-based view. Whitespace is the only text
normalization tolerated. Any disagreement, any pypdf exception and any cap
hit refuses (``CrossCheckError`` / ``LimitExceededError``).
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

from pypdf import PdfReader

from pursue_index.pdf_limits import Budget, LimitExceededError

__all__ = ["CROSSCHECKS", "CrossCheckError", "crosscheck"]

CROSSCHECKS = ("content-streams", "text")


class CrossCheckError(Exception):
    """A cross-check signal disagreed (or pypdf could not answer)."""

    def __init__(self, signal: str, detail: str = "") -> None:
        super().__init__(f"{signal}: {detail}" if detail else signal)
        self.signal = signal


def _page_digest(page: Any, budget: Budget) -> str:
    contents = page.get_object().get("/Contents")
    contents = contents.get_object() if contents is not None else None
    streams = contents if isinstance(contents, list) else [contents]
    digest = hashlib.sha256()
    for item in streams:
        stream = item.get_object() if item is not None else None
        raw = getattr(stream, "_data", b"") if stream is not None else b""
        head = repr((stream.get("/Filter"), stream.get("/DecodeParms"))) if stream is not None else ""
        digest.update(len(raw).to_bytes(8, "big") + head.encode() + b"\0" + raw)
    return digest.hexdigest()


def _page_text(page: Any, budget: Budget) -> str:
    # extract_text inflates the page's content streams; charge that output to
    # the same total-inflated-bytes budget the xref parser draws on.
    contents = page.get_object().get("/Contents")
    contents = contents.get_object() if contents is not None else None
    for item in contents if isinstance(contents, list) else [contents]:
        if item is not None:
            budget.charge(len(item.get_object().get_data()))
    return " ".join(page.extract_text().split())


def _compare(signal: str, per_page: Any, old: PdfReader, new: PdfReader, budget: Budget) -> None:
    for number, (a, b) in enumerate(zip(old.pages, new.pages, strict=True)):
        budget.check()
        if per_page(a, budget) != per_page(b, budget):
            raise CrossCheckError(signal, f"page {number} differs")


def crosscheck(old: bytes, new: bytes, budget: Budget) -> tuple[str, ...]:
    """The signals that agreed (all of ``CROSSCHECKS``), else an error."""
    try:
        old_reader = PdfReader(io.BytesIO(old))
        new_reader = PdfReader(io.BytesIO(new))
        if len(old_reader.pages) != len(new_reader.pages):
            raise CrossCheckError("content-streams", "page count differs")
        _compare("content-streams", _page_digest, old_reader, new_reader, budget)
        _compare("text", _page_text, old_reader, new_reader, budget)
    except (CrossCheckError, LimitExceededError):
        raise
    except Exception as exc:  # noqa: BLE001 -- pypdf cannot answer: refuse
        raise CrossCheckError("pypdf", repr(exc)) from exc
    return CROSSCHECKS
