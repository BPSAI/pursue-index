"""Adversarial shapes ``classify_bytes`` must call ``content-changed``.

Each case is an appended update that a metadata-only re-save would never
produce, or one that re-uses metadata-looking objects to change what the
document renders. A wrong ``metadata-only`` here would auto-alias a card
whose content changed, so every ambiguous shape fails closed.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import (
    append_update,
    build_base_pdf,
    catalog_body,
    info_body,
    last_startxref,
    metadata_only_resave,
    stream_body,
    write_pair,
    xmp_body,
)

CC = "content-changed"


def _verdict(tmp_path: Path, old: bytes, new: bytes) -> str:
    return classify_bytes(*write_pair(tmp_path, old, new))


def test_prev_not_pointing_at_old_startxref(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.size: info_body()}, root=base.root_num,
                        info=base.size, size=base.size + 1, prev=9)
    assert _verdict(tmp_path, base.data, new) == CC


def test_appended_garbage_is_not_an_update(tmp_path: Path) -> None:
    base = build_base_pdf()
    assert _verdict(tmp_path, base.data, base.data + b"\nnot a pdf update\n") == CC


def test_undeclared_object_hidden_in_the_update(tmp_path: Path) -> None:
    base = build_base_pdf()
    hidden = b"%d 0 obj\n" % base.contents_num + stream_body(b"(EDIT) Tj") + b"\nendobj\n"
    new = append_update(base.data, {base.size: info_body()}, root=base.root_num,
                        info=base.size, size=base.size + 1, extra=hidden)
    assert _verdict(tmp_path, base.data, new) == CC


def test_two_stacked_updates(tmp_path: Path) -> None:
    base = build_base_pdf()
    once = metadata_only_resave(base, xref_stream=False)
    twice = append_update(once, {base.size + 5: info_body(b"again")}, root=base.root_num,
                          info=base.size + 5, size=base.size + 6,
                          prev=last_startxref(once))
    assert _verdict(tmp_path, base.data, twice) == CC


def test_catalog_change_beyond_metadata_pointer(tmp_path: Path) -> None:
    base = build_base_pdf()
    catalog = catalog_body(base, Metadata=base.metadata_num, OpenAction=base.contents_num)
    new = append_update(base.data, {base.root_num: catalog}, root=base.root_num,
                        info=base.info_num, size=base.size)
    assert _verdict(tmp_path, base.data, new) == CC


def test_content_stream_number_reused_as_xmp(tmp_path: Path) -> None:
    """An old content stream rewritten with ``/Type /Metadata`` still
    renders as the page's content -- the role must match the old one."""
    base = build_base_pdf()
    new = append_update(base.data, {base.contents_num: xmp_body()}, root=base.root_num,
                        info=base.info_num, size=base.size)
    assert _verdict(tmp_path, base.data, new) == CC


def test_info_pointer_hijacking_an_old_object(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.image_num: info_body()}, root=base.root_num,
                        info=base.image_num, size=base.size)
    assert _verdict(tmp_path, base.data, new) == CC


def test_freed_content_object(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.size: info_body()}, root=base.root_num,
                        info=base.size, size=base.size + 1, free=(base.image_num,))
    assert _verdict(tmp_path, base.data, new) == CC


def test_root_switched_to_another_old_object(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.size: info_body()}, root=base.info_num,
                        info=base.size, size=base.size + 1)
    assert _verdict(tmp_path, base.data, new) == CC


def test_unreferenced_new_leaf_object(tmp_path: Path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.size: info_body(), base.size + 1: b"42"},
                        root=base.root_num, info=base.size, size=base.size + 2)
    assert _verdict(tmp_path, base.data, new) == CC


def test_new_non_metadata_dictionary(tmp_path: Path) -> None:
    base = build_base_pdf()
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 9 9] >>"
    new = append_update(base.data, {base.size: info_body(), base.size + 1: page},
                        root=base.root_num, info=base.size, size=base.size + 2)
    assert _verdict(tmp_path, base.data, new) == CC


def test_non_pdf_old_bytes(tmp_path: Path) -> None:
    assert _verdict(tmp_path, b"plain text\n", b"plain text\nmore text\n") == CC
