"""Tests for the encoding-only change detector (#157).

Upstream has served the same CSV content in two byte encodings: the
``c3f8209ef5f5`` file is UTF-8 (with BOM) and ``e1f9fec8d74a`` is the same
rows exported as Mac Roman, where characters Mac Roman cannot hold (U+202F
narrow no-break space) became ``_``. That pair must compare as
encoding-only; ``19e6dd7a69d5`` -> ``e1f9fec8d74a`` also carries real row
changes and must not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.scrape.encoding_equivalence import is_encoding_only_change

_CSV_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "csv"
_SHA_19E6 = "19e6dd7a69d5c41c30bc3d9302462e922c6225cf18649298b329e68918e28a20"
_SHA_E1F9 = "e1f9fec8d74a1044f11c2fa1f5be53937cbab78485ec90d045d2ed06ca491fb5"
_SHA_C3F8 = "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7"


def _raw(sha: str) -> bytes:
    return (_CSV_DIR / f"{sha}.csv").read_bytes()


def test_committed_e1f9_and_c3f8_are_encoding_only_both_directions() -> None:
    assert is_encoding_only_change(_raw(_SHA_E1F9), _raw(_SHA_C3F8))
    assert is_encoding_only_change(_raw(_SHA_C3F8), _raw(_SHA_E1F9))


def test_committed_19e6_to_e1f9_is_not_encoding_only() -> None:
    assert not is_encoding_only_change(_raw(_SHA_19E6), _raw(_SHA_E1F9))


def test_committed_19e6_to_c3f8_is_not_encoding_only() -> None:
    assert not is_encoding_only_change(_raw(_SHA_19E6), _raw(_SHA_C3F8))


_HEADER = "Title,Description Blurb\r\n"


def _utf8(body: str) -> bytes:
    return ("\ufeff" + _HEADER + body).encode("utf-8")


def test_nbsp_versus_space_is_encoding_only() -> None:
    old = _utf8('"A\u00a0case","said \u201chi\u201d"\r\n')
    new = _utf8('"A case","said \u201chi\u201d"\r\n')
    assert is_encoding_only_change(old, new)


def test_nfd_versus_nfc_is_encoding_only() -> None:
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
