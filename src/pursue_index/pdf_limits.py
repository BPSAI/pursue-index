"""Resource caps for the hand-rolled PDF update parser.

``classify_bytes`` runs on externally sourced PDFs, so a crafted file must
not be able to spend unbounded memory or time. Every cap raises
``LimitExceededError``; ``classify_bytes`` turns that into ``content-changed``
(the fail-safe class: the row stays quarantined for an operator) with the
``reason`` logged -- a cap hit can never produce ``metadata-only``.

The constants are read at call time so tests can lower them.
"""

from __future__ import annotations

import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pypdf import apply_configuration
from pypdf.errors import LimitReachedError, PyPdfError

__all__ = [
    "Budget",
    "LimitExceededError",
    "capped_pypdf",
    "check_update_count",
    "inflate_capped",
    "read_capped",
]

# Largest PDF in data/asset-bytes-registry.jsonl is ~370 MB; 512 MiB leaves
# ~45% margin. Both files are read whole, so this bounds peak memory.
MAX_FILE_BYTES = 512 * 1024 * 1024
# A legitimate xref stream is ~7 bytes per object; 8 MiB covers ~1M objects.
MAX_XREF_INFLATED = 8 * 1024 * 1024
MAX_XREF_ENTRIES = 1_000_000
MAX_TOTAL_INFLATED = 16 * 1024 * 1024
# The update chain pypdf walks (and this module refuses beyond one new section).
MAX_UPDATES = 16
TIME_BUDGET_SECONDS = 30.0


class LimitExceededError(Exception):
    """A resource cap was hit; ``reason`` is the short code that gets logged."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class Budget:
    """A monotonic deadline plus a total-inflated-bytes allowance."""

    def __init__(self) -> None:
        self._deadline = time.monotonic() + TIME_BUDGET_SECONDS
        self._left = MAX_TOTAL_INFLATED

    def check(self) -> None:
        if time.monotonic() >= self._deadline:
            raise LimitExceededError("time-budget", f"over {TIME_BUDGET_SECONDS}s")

    def charge(self, nbytes: int) -> None:
        self._left -= nbytes
        if self._left < 0:
            raise LimitExceededError("total-bytes-budget", f"over {MAX_TOTAL_INFLATED}")


def read_capped(path: Path) -> bytes:
    """``path``'s bytes, refusing (before any read) a file over the cap."""
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise LimitExceededError("file-size-cap", f"{size} > {MAX_FILE_BYTES}")
    return path.read_bytes()


def inflate_capped(data: bytes, budget: Budget) -> bytes:
    """zlib-inflate ``data``, aborting once the output passes the cap."""
    out = zlib.decompressobj().decompress(data, MAX_XREF_INFLATED + 1)
    if len(out) > MAX_XREF_INFLATED:
        raise LimitExceededError("xref-inflate-cap", f"over {MAX_XREF_INFLATED}")
    budget.charge(len(out))
    return out


def check_update_count(data: bytes) -> None:
    """Refuse a file whose ``startxref`` chain is longer than the cap."""
    count = data.count(b"startxref")
    if count > MAX_UPDATES:
        raise LimitExceededError("update-count", f"{count} > {MAX_UPDATES}")


@contextmanager
def capped_pypdf() -> Iterator[None]:
    """Cap pypdf's own zlib output while it walks the xref chain.

    ``PdfReader`` inflates every xref stream it meets (old file's included)
    before this module's parser runs; its default cap is 75 MB per stream.
    """
    try:
        with apply_configuration(zlib_maximum_output_length=MAX_XREF_INFLATED):
            yield
    except PyPdfError as exc:
        cause: BaseException | None = exc
        while cause is not None:  # pypdf wraps the limit error in PdfReadError
            if isinstance(cause, LimitReachedError):
                raise LimitExceededError("xref-inflate-cap", f"pypdf: {cause}") from exc
            cause = cause.__cause__
        raise
