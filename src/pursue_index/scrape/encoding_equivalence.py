"""Detect upstream CSV changes that only re-encode the same text.

Upstream has re-exported CSV content in a different byte encoding (the Mac
Roman ``e1f9fec8d74a`` next to the UTF-8 ``c3f8209ef5f5``). A change that
only re-encodes the same characters is not a new tranche.

Rule: decode each file with its own encoding (UTF-8 when the bytes are
valid UTF-8, otherwise each legacy codec in ``LEGACY_CODECS``), apply
Unicode NFC to every CSV cell, and require every cell to be exactly equal.
There is no whitespace folding: a collapsed double space, a trimmed
leading/trailing space or NBSP-vs-space is a real metadata change. So is a
character a legacy codec couldn't hold being replaced on export (``e1f9``
wrote ``_`` for U+202F), which is why ``e1f9`` -> ``c3f8`` is a real change.

``is_encoding_only_change`` is comparison-only: it decodes and compares in
memory and never alters the bytes it is given.
"""

from __future__ import annotations

import csv
import io
import unicodedata

LEGACY_CODECS: tuple[str, ...] = ("mac_roman", "cp1252")


def is_encoding_only_change(old: bytes, new: bytes) -> bool:
    """True when ``old`` and ``new`` decode to the same NFC text, cell by cell.

    Both orders give the same answer. Two valid-UTF-8 files are equivalent
    only when NFC composition is their sole difference.
    """
    new_rows = [_rows(text) for text in _decodings(new)]
    return any(_rows(old_text) in new_rows for old_text in _decodings(old))


def _decodings(raw: bytes) -> list[str]:
    """Candidate texts: the UTF-8 decoding when valid (unambiguous), else
    one per legacy codec that decodes the bytes."""
    try:
        return [raw.decode("utf-8-sig")]
    except UnicodeDecodeError:
        pass
    out: list[str] = []
    for codec in LEGACY_CODECS:
        try:
            out.append(raw.decode(codec))
        except UnicodeDecodeError:
            continue
    return out


def _rows(text: str) -> list[list[str]]:
    return [
        [unicodedata.normalize("NFC", cell) for cell in row]
        for row in csv.reader(io.StringIO(text))
    ]
