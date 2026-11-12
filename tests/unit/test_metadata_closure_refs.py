"""The "referenced from nowhere else" rule covers the whole metadata closure:
a new leaf owned by the Info dict or the XMP stream must not also be named
by anything else -- an old page, another update object, the raw old bytes."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject, NameObject

from pursue_index.pdf_limits import Budget
from pursue_index.pdf_refs import raw_reference_in, referenced_outside
from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import (
    XMP_TEMPLATE,
    append_update,
    build_base_pdf,
    catalog_body,
    stream_body,
    write_pair,
    xmp_body,
)


def _verdict(tmp_path: Path, old: bytes, new: bytes) -> str:
    return classify_bytes(*write_pair(tmp_path, old, new), isolated=False)


def _old_with_dangling_page_ref(key: str = "/Rotate"):
    """The base plus an update giving the page ``key -> <undefined number>``."""
    base = build_base_pdf()
    reader = PdfReader(io.BytesIO(base.data))
    page_num = reader.pages[0].indirect_reference.idnum
    page = DictionaryObject(reader.pages[0].get_object())
    page[NameObject(key)] = IndirectObject(base.size, 0, reader)
    buf = io.BytesIO()
    page.write_to_stream(buf)
    old = append_update(base.data, {page_num: buf.getvalue()}, root=base.root_num,
                        info=base.info_num, size=base.size)
    return base, old, base.size


def test_defining_a_number_an_old_page_names_is_content_changed_even_via_info(tmp_path) -> None:
    base, old, dangling = _old_with_dangling_page_ref()
    info = dangling + 1
    new = append_update(old, {dangling: b"90",
                              info: b"<< /Title (DOW-UAP-D042) /Subject %d 0 R >>" % dangling},
                        root=base.root_num, info=info, size=info + 1)
    assert _verdict(tmp_path, old, new) == "content-changed"


def test_defining_it_via_the_xmp_length_is_content_changed(tmp_path) -> None:
    base, old, dangling = _old_with_dangling_page_ref()
    data = XMP_TEMPLATE % b"2024-06-01"
    xmp = dangling + 1
    objects = {
        dangling: b"%d" % len(data),
        xmp: stream_body(data, b"/Type /Metadata /Subtype /XML", b"%d 0 R" % dangling),
        base.root_num: catalog_body(base, Metadata=xmp),
    }
    new = append_update(old, objects, root=base.root_num, info=base.info_num, size=xmp + 1)
    assert _verdict(tmp_path, old, new) == "content-changed"


def test_an_info_owned_leaf_nothing_else_names_stays_metadata_only(tmp_path) -> None:
    base = build_base_pdf()
    leaf, info = base.size, base.size + 1
    new = append_update(base.data, {leaf: b"(DOW-UAP-D042)", info: b"<< /Title %d 0 R >>" % leaf},
                        root=base.root_num, info=info, size=info + 1)
    assert _verdict(tmp_path, base.data, new) == "metadata-only"


def test_an_xmp_owned_length_leaf_stays_metadata_only(tmp_path) -> None:
    base = build_base_pdf()
    leaf, xmp = base.size, base.size + 1
    data = XMP_TEMPLATE % b"2024-06-01"
    objects = {
        leaf: b"%d" % len(data),
        xmp: stream_body(data, b"/Type /Metadata /Subtype /XML", b"%d 0 R" % leaf),
        base.root_num: catalog_body(base, Metadata=xmp),
    }
    new = append_update(base.data, objects, root=base.root_num, info=base.info_num, size=xmp + 1)
    assert _verdict(tmp_path, base.data, new) == "metadata-only"


def test_a_leaf_with_no_metadata_owner_is_content_changed(tmp_path) -> None:
    base = build_base_pdf()
    new = append_update(base.data, {base.size: b"90"}, root=base.root_num,
                        info=base.info_num, size=base.size + 1)
    assert _verdict(tmp_path, base.data, new) == "content-changed"


def test_raw_reference_in_matches_whole_numbers_only() -> None:
    budget = Budget()
    assert raw_reference_in(b"/Rotate 12 0 R >>", {12}, budget)
    assert raw_reference_in(b"/Length 12  0\nR\n", {12}, budget)
    assert not raw_reference_in(b"/Rotate 112 0 R", {12}, budget)
    assert not raw_reference_in(b"/Rotate 12.0 0 R", {0}, budget)
    assert not raw_reference_in(b"1 0 0 12 0 RG", {12}, budget)
    assert not raw_reference_in(b"anything", set(), budget)


def test_referenced_outside_honours_the_allowed_owners() -> None:
    _base, old, dangling = _old_with_dangling_page_ref()
    reader = PdfReader(io.BytesIO(old))
    page_num = reader.pages[0].indirect_reference.idnum
    assert referenced_outside({dangling}, set(), reader, Budget())
    assert not referenced_outside({dangling}, {page_num}, reader, Budget())
    assert not referenced_outside(set(), set(), reader, Budget())


def test_xmp_body_helper_still_classifies(tmp_path) -> None:
    """Guard for the fixture itself: a plain XMP rewrite is metadata-only."""
    base = build_base_pdf()
    new = append_update(base.data, {base.metadata_num: xmp_body()}, root=base.root_num,
                        info=base.info_num, size=base.size)
    assert _verdict(tmp_path, base.data, new) == "metadata-only"


def test_raw_reference_in_scales_to_many_targets_with_one_fixed_pattern(monkeypatch) -> None:
    import re

    from pursue_index import pdf_refs

    compiled: list[bytes] = []
    real_compile = re.compile

    def spy(pattern, *a, **k):  # type: ignore[no-untyped-def]
        compiled.append(pattern)
        return real_compile(pattern, *a, **k)

    monkeypatch.setattr(pdf_refs.re, "compile", spy)
    targets = set(range(100_000, 400_000))
    data = b"/Kids [1 0 R 2 0 R] /Rotate 399999 0 R"
    assert raw_reference_in(data, targets, Budget())
    assert not raw_reference_in(b"/Kids [1 0 R 2 0 R]", targets, Budget())
    assert compiled == []  # no pattern built per call, however many targets


def test_raw_reference_scan_checks_the_budget_as_it_goes(monkeypatch) -> None:
    from pursue_index import pdf_refs
    from pursue_index.pdf_limits import LimitExceededError

    class Counting(Budget):
        calls = 0

        def check(self) -> None:
            Counting.calls += 1
            if Counting.calls > 3:
                raise LimitExceededError("time-budget", "test")

    monkeypatch.setattr(pdf_refs, "_RAW_SCAN_CHECK_EVERY", 10)
    data = b" ".join(b"%d 0 R" % n for n in range(1, 200))
    try:
        raw_reference_in(data, {999_999}, Counting())
    except LimitExceededError:
        return
    raise AssertionError("budget never interrupted the scan")


def test_raw_reference_in_ignores_an_overlong_digit_run() -> None:
    assert not raw_reference_in(b"9" * 5000 + b" 0 R", {12}, Budget())
    assert raw_reference_in(b"9" * 5000 + b" 12 0 R", {12}, Budget())


def test_raw_reference_in_sees_through_comments_and_pdf_whitespace() -> None:
    budget = Budget()
    assert raw_reference_in(b"/Rotate 12%comment\n0 R >>", {12}, budget)
    assert raw_reference_in(b"/Rotate 12 0%c1\r%c2\nR", {12}, budget)
    assert raw_reference_in(b"/Rotate 12\x000\x0cR", {12}, budget)
    assert not raw_reference_in(b"/Rotate 12%comment 0 R", {12}, budget)  # same line: a comment
    assert not raw_reference_in(b"/Rotate 112%c\n0 R", {12}, budget)


def test_raw_reference_separator_stays_linear_on_many_comments() -> None:
    import time
    data = b"12" + b"%" * 20000 + b"x"  # no EOL, no R: must fail fast
    start = time.monotonic()
    assert not raw_reference_in(data, {12}, Budget())
    assert time.monotonic() - start < 1.0


def _with_generation_one_object(base_data: bytes, num: int, body: bytes, *, root: int,
                                info: int | None, size: int) -> bytes:
    """``base_data`` plus an update defining object ``num`` at generation 1."""
    from tests.support.tranche_bytes_fakes import last_startxref

    out = bytearray(base_data if base_data.endswith(b"\n") else base_data + b"\n")
    at_obj = len(out)
    out += b"%d 1 obj\n" % num + body + b"\nendobj\n"
    at = len(out)
    info_ref = b" /Info %d 0 R" % info if info is not None else b""
    out += b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d 00001 n \n" % (num, at_obj)
    out += b"trailer\n<< /Size %d /Root %d 0 R%s /Prev %d >>\n" % (
        max(size, num + 1), root, info_ref, last_startxref(base_data))
    out += b"startxref\n%d\n%%%%EOF\n" % at
    return bytes(out)


def test_referenced_outside_reads_a_generation_one_object_as_itself() -> None:
    base = build_base_pdf()
    target = base.size  # a number nothing defines yet
    holder = base.size + 1
    data = _with_generation_one_object(
        base.data, holder, b"<< /Rotate %d 0 R >>" % target,
        root=base.root_num, info=base.info_num, size=base.size + 2)
    reader = PdfReader(io.BytesIO(data))
    assert 1 in reader.xref and holder in reader.xref[1]
    assert referenced_outside({target}, set(), reader, Budget())
    assert not referenced_outside({target}, {holder}, reader, Budget())
