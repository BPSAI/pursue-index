"""Tests for the encoding-only change detector (#157).

"Encoding-only" means: decode each file with its own encoding (UTF-8 when
valid, else a legacy codec), apply NFC, and every CSV cell is exactly
equal. No whitespace folding: a whitespace edit is a real metadata change.

Upstream's ``e1f9fec8d74a`` is a Mac Roman export of the content in the
UTF-8 ``c3f8209ef5f5``. Their no-break spaces decode to the same U+00A0,
but the export is also lossy (U+202F narrow no-break space, which Mac Roman
cannot hold, became ``_``) and carries one trailing space ``c3f8`` lacks,
so the real pair is NOT encoding-only. The same export with those cells
repaired is.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from pathlib import Path

import pytest

from pursue_index.scrape.encoding_equivalence import is_encoding_only_change

_CSV_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "csv"
_SHA_19E6 = "19e6dd7a69d5c41c30bc3d9302462e922c6225cf18649298b329e68918e28a20"
_SHA_E1F9 = "e1f9fec8d74a1044f11c2fa1f5be53937cbab78485ec90d045d2ed06ca491fb5"
_SHA_C3F8 = "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7"


def _raw(sha: str) -> bytes:
    return (_CSV_DIR / f"{sha}.csv").read_bytes()


def _cells(raw: bytes, codec: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(raw.decode(codec))))


def _differing_cells(a: list[list[str]], b: list[list[str]]) -> list[tuple[int, int]]:
    return [
        (i, j)
        for i, (ra, rb) in enumerate(zip(a, b, strict=True))
        for j, (ca, cb) in enumerate(zip(ra, rb, strict=True))
        if unicodedata.normalize("NFC", ca) != unicodedata.normalize("NFC", cb)
    ]


def test_committed_e1f9_and_c3f8_are_not_encoding_only_both_directions() -> None:
    """(e) The real pair: lossy ``_`` for U+202F plus one trimmed trailing
    space are text differences, so this is a real change (fail closed)."""
    assert not is_encoding_only_change(_raw(_SHA_E1F9), _raw(_SHA_C3F8))
    assert not is_encoding_only_change(_raw(_SHA_C3F8), _raw(_SHA_E1F9))


def test_committed_e1f9_c3f8_differ_only_in_the_four_known_cells() -> None:
    """Pins why (e) is a real change: NBSP bytes (Mac Roman 0xCA, UTF-8
    C2 A0) agree once each file is decoded; exactly four cells don't."""
    mac = _cells(_raw(_SHA_E1F9), "mac_roman")
    utf = _cells(_raw(_SHA_C3F8), "utf-8-sig")
    diffs = _differing_cells(mac, utf)
    assert len(diffs) == 4
    for i, j in diffs:
        a, b = mac[i][j], utf[i][j]
        assert a.replace("_", "\u202f") == b or a.rstrip() == b.rstrip()
    assert "\u00a0" in "".join(c for row in mac for c in row)


def test_committed_e1f9_with_its_text_differences_repaired_is_encoding_only() -> None:
    """(e') The Mac Roman export itself (curly quotes, 0xCA no-break
    spaces, no BOM) is encoding-only against the UTF-8 file once the four
    real text differences are put back."""
    mac = _cells(_raw(_SHA_E1F9), "mac_roman")
    utf = _cells(_raw(_SHA_C3F8), "utf-8-sig")
    text = _raw(_SHA_E1F9).decode("mac_roman")
    for i, j in _differing_cells(mac, utf):
        # Each differing cell is unique in the file; swap it for the UTF-8
        # cell with U+202F spelled as NBSP (Mac Roman can encode that).
        assert text.count(mac[i][j]) == 1
        text = text.replace(mac[i][j], utf[i][j].replace("\u202f", "\u00a0"))
    repaired = text.encode("mac_roman")
    c3f8_nbsp = _raw(_SHA_C3F8).decode("utf-8-sig").replace("\u202f", "\u00a0")
    utf8_version = ("\ufeff" + c3f8_nbsp).encode("utf-8")
    assert is_encoding_only_change(repaired, utf8_version)
    assert is_encoding_only_change(utf8_version, repaired)


def test_committed_19e6_to_e1f9_is_not_encoding_only() -> None:
    """(f)"""
    assert not is_encoding_only_change(_raw(_SHA_19E6), _raw(_SHA_E1F9))


def test_committed_19e6_to_c3f8_is_not_encoding_only() -> None:
    assert not is_encoding_only_change(_raw(_SHA_19E6), _raw(_SHA_C3F8))


_HEADER = "Title,Description Blurb\r\n"


def _utf8(body: str) -> bytes:
    return ("\ufeff" + _HEADER + body).encode("utf-8")


@pytest.mark.parametrize(
    ("old_body", "new_body"),
    [
        ('"foo  bar",x\r\n', '"foo bar",x\r\n'),  # (a) collapsed double space
        ('"foo bar ",x\r\n', '"foo bar",x\r\n'),  # (b) trailing space trimmed
        ('" foo bar",x\r\n', '"foo bar",x\r\n'),  # (b) leading space trimmed
        ('"foo\u00a0bar",x\r\n', '"foo bar",x\r\n'),  # (c) NBSP vs ASCII space
        ('"foo\u202fbar",x\r\n', '"foo\u00a0bar",x\r\n'),  # (c) other whitespace variant
    ],
)
def test_utf8_whitespace_edits_are_real_changes(old_body: str, new_body: str) -> None:
    """(a)-(c): both files valid UTF-8, bytes differ, NFC doesn't equalize."""
    assert not is_encoding_only_change(_utf8(old_body), _utf8(new_body))
    assert not is_encoding_only_change(_utf8(new_body), _utf8(old_body))


def test_nfd_versus_nfc_is_encoding_only() -> None:
    """(d)"""
    old = _utf8('"Caf\u00e9",x\r\n')
    new = _utf8('"Cafe\u0301",x\r\n')
    assert is_encoding_only_change(old, new)


def test_cp1252_export_of_same_text_is_encoding_only() -> None:
    text = _HEADER + '"It\u2019s a \u201ctest\u201d",x\r\n'
    assert is_encoding_only_change(("\ufeff" + text).encode("utf-8"), text.encode("cp1252"))


@pytest.mark.parametrize(
    "new_body",
    [
        '"A case","said hi"\r\n',  # quotes removed: a text change
        '"A case","said \u201chi\u201d"\r\n"B",y\r\n',  # a row added
        '"A_case","said \u201chi\u201d"\r\n',  # underscore where UTF-8 had a plain space
    ],
)
def test_real_text_changes_are_not_encoding_only(new_body: str) -> None:
    old = _utf8('"A case","said \u201chi\u201d"\r\n')
    assert not is_encoding_only_change(old, _utf8(new_body))


def test_does_not_mutate_inputs() -> None:
    old = _raw(_SHA_E1F9)
    new = _raw(_SHA_C3F8)
    before = (bytes(old), bytes(new))
    is_encoding_only_change(old, new)
    assert (old, new) == before
