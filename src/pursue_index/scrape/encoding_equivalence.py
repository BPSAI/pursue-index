"""Detect upstream CSV changes that only re-encode the same text.

Upstream has re-exported the same rows in a different byte encoding: the
UTF-8 file ``c3f8209ef5f5`` and the Mac Roman file ``e1f9fec8d74a`` carry
identical content, differing in how curly quotes and no-break spaces are
encoded (Mac Roman cannot hold U+202F, so that exporter wrote ``_``). A
change like that is not a new tranche.

``is_encoding_only_change`` is comparison-only: it decodes, normalizes and
compares in memory and never alters the bytes it is given.

Normalization, per CSV cell: Unicode NFC, then every whitespace variant
(NBSP, narrow NBSP, thin space, line separators, ...) folded to one plain
space, runs collapsed, ends stripped. Bytes that are not valid UTF-8 are
tried as each legacy codec in ``LEGACY_CODECS``; when one side is legacy,
whitespace the legacy codec cannot represent may appear there as one of
``UNENCODABLE_PLACEHOLDERS``. Anything else that differs is a real change.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata

LEGACY_CODECS: tuple[str, ...] = ("mac_roman", "cp1252")
UNENCODABLE_PLACEHOLDERS: tuple[str, ...] = ("_", "?", "")

_WS_RUN = re.compile(r"\s+")


def is_encoding_only_change(old: bytes, new: bytes) -> bool:
    """True when ``old`` and ``new`` decode to the same text modulo encoding.

    Both orders give the same answer. Returns ``False`` whenever no
    combination of decodings makes the normalized rows equal.
    """
    for old_codec, old_text in _decodings(old):
        for new_codec, new_text in _decodings(new):
            if _equivalent(old_codec, old_text, new_codec, new_text):
                return True
    return False


def _decodings(raw: bytes) -> list[tuple[str | None, str]]:
    """``(codec, text)`` candidates; codec ``None`` means valid UTF-8.

    Valid UTF-8 is unambiguous, so it is the only candidate when it decodes.
    """
    try:
        return [(None, raw.decode("utf-8-sig"))]
    except UnicodeDecodeError:
        pass
    out: list[tuple[str | None, str]] = []
    for codec in LEGACY_CODECS:
        try:
            out.append((codec, raw.decode(codec)))
        except UnicodeDecodeError:
            continue
    return out


def _equivalent(old_codec: str | None, old_text: str, new_codec: str | None, new_text: str) -> bool:
    if (old_codec is None) == (new_codec is None):
        return _rows(old_text) == _rows(new_text)
    unicode_text, legacy_codec, legacy_text = (
        (old_text, new_codec, new_text) if old_codec is None else (new_text, old_codec, old_text)
    )
    assert legacy_codec is not None
    legacy_rows = _rows(legacy_text)
    return any(
        _rows(_substitute_unencodable_whitespace(unicode_text, legacy_codec, ph)) == legacy_rows
        for ph in UNENCODABLE_PLACEHOLDERS
    )


def _substitute_unencodable_whitespace(text: str, codec: str, placeholder: str) -> str:
    """Replace whitespace ``codec`` can't encode with ``placeholder``."""
    return "".join(
        placeholder if ch.isspace() and not _encodable(ch, codec) else ch for ch in text
    )


def _encodable(ch: str, codec: str) -> bool:
    try:
        ch.encode(codec)
    except UnicodeEncodeError:
        return False
    return True


def _rows(text: str) -> list[list[str]]:
    return [[_normalize_cell(cell) for cell in row] for row in csv.reader(io.StringIO(text))]


def _normalize_cell(cell: str) -> str:
    return _WS_RUN.sub(" ", unicodedata.normalize("NFC", cell)).strip()
