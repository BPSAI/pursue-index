"""Synthetic PDFs for ``pursue_index.tranche_bytes``: a base file plus
hand-built incremental updates.

The base PDF is written by ``pypdf.PdfWriter`` (Info dict, XMP metadata
stream, one page with a content stream that paints one embedded image).
Incremental updates are appended byte-for-byte here -- never by pypdf --
so a test controls exactly which objects an update touches.

``append_update`` takes ``{objnum: body}``, where ``body`` is the raw PDF
syntax between ``N 0 obj`` and ``endobj``. The ``*_body`` helpers build the
bodies the real D042 re-save carried (new Info, new XMP stream, catalog
re-pointed at the new XMP stream) and the content-changing variant (a
replacement page ``/Contents`` stream).
"""

from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
)

XMP_TEMPLATE = (
    b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b"<rdf:Description xmlns:xmp=\"http://ns.adobe.com/xap/1.0/\"><xmp:ModifyDate>%s</xmp:ModifyDate>"
    b"</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
)


@dataclass(frozen=True)
class BasePdf:
    data: bytes
    root_num: int
    info_num: int
    metadata_num: int
    contents_num: int
    image_num: int
    size: int


def _stream(data: bytes, **entries: object) -> DecodedStreamObject:
    s = DecodedStreamObject()
    s.set_data(data)
    for key, value in entries.items():
        s[NameObject(f"/{key}")] = value
    return s


def build_base_pdf(text: bytes = b"(D042 debrief) Tj") -> BasePdf:
    """A one-page PDF with Info, XMP, a content stream and an image."""
    w = PdfWriter()
    page = w.add_blank_page(width=200, height=200)
    image = _stream(bytes(range(16)), Type=NameObject("/XObject"),
                    Subtype=NameObject("/Image"), Width=NumberObject(4),
                    Height=NumberObject(4), ColorSpace=NameObject("/DeviceGray"),
                    BitsPerComponent=NumberObject(8))
    image_ref = w._add_object(image)
    contents = _stream(b"q 100 0 0 100 0 0 cm /Im0 Do Q BT /F1 9 Tf " + text + b" ET")
    contents_ref = w._add_object(contents)
    page[NameObject("/Contents")] = contents_ref
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref}),
    })
    xmp = _stream(XMP_TEMPLATE % b"2023-01-01", Type=NameObject("/Metadata"),
                  Subtype=NameObject("/XML"))
    metadata_ref = w._add_object(xmp)
    w.root_object[NameObject("/Metadata")] = metadata_ref
    w.add_metadata({"/Title": "DOW-UAP-D042", "/Producer": "base"})
    buf = io.BytesIO()
    w.write(buf)
    data = buf.getvalue()
    reader = PdfReader(io.BytesIO(data))
    return BasePdf(
        data=data,
        root_num=reader.trailer.raw_get("/Root").idnum,
        info_num=reader.trailer.raw_get("/Info").idnum,
        metadata_num=metadata_ref.idnum,
        contents_num=contents_ref.idnum,
        image_num=image_ref.idnum,
        size=int(reader.trailer["/Size"]),
    )


def last_startxref(data: bytes) -> int:
    return int(re.findall(rb"startxref\s+(\d+)", data)[-1])


def info_body(producer: bytes = b"resave") -> bytes:
    return b"<< /Title (DOW-UAP-D042) /Producer (" + producer + b") >>"


def stream_body(data: bytes, entries: bytes = b"", length: bytes | None = None) -> bytes:
    length = length if length is not None else str(len(data)).encode()
    return b"<< " + entries + b" /Length " + length + b" >>\nstream\n" + data + b"\nendstream"


def xmp_body(date: bytes = b"2024-06-01", length: bytes | None = None) -> bytes:
    return stream_body(XMP_TEMPLATE % date, b"/Type /Metadata /Subtype /XML", length)


def catalog_body(base: BasePdf, **overrides: int) -> bytes:
    """The base catalog re-serialized, each ``Key=objnum`` override set to
    ``objnum 0 R`` (e.g. ``Metadata=12`` re-points the XMP pointer)."""
    reader = PdfReader(io.BytesIO(base.data))
    catalog = DictionaryObject(reader.trailer["/Root"].get_object())
    for key, num in overrides.items():
        catalog[NameObject(f"/{key}")] = IndirectObject(num, 0, reader)
    buf = io.BytesIO()
    catalog.write_to_stream(buf)
    return buf.getvalue()


def _xref_table(offsets: dict[int, int], free: tuple[int, ...]) -> bytes:
    rows = {0: b"0000000000 65535 f \n"}
    rows.update({n: b"0000000000 00001 f \n" for n in free})
    rows.update({n: b"%010d 00000 n \n" % off for n, off in offsets.items()})
    out = b"xref\n"
    for n in sorted(rows):
        out += b"%d 1\n" % n + rows[n]
    return out


def _xref_stream(num: int, at: int, offsets: dict[int, int], trailer: bytes,
                 flate: bool) -> bytes:
    entries = {**offsets, num: at}
    raw = b"".join(b"\x01" + off.to_bytes(4, "big") + b"\x00\x00"
                   for _, off in sorted(entries.items()))
    index = b" ".join(b"%d 1" % n for n in sorted(entries))
    data = zlib.compress(raw) if flate else raw
    filt = b" /Filter /FlateDecode" if flate else b""
    head = (b"<< /Type /XRef /W [1 4 2] /Index [" + index + b"] " + trailer + filt
            + b" /Length %d >>\nstream\n" % len(data))
    return b"%d 0 obj\n" % num + head + data + b"\nendstream\nendobj\n"


def append_update(
    base: bytes, objects: dict[int, bytes], *, root: int, info: int | None,
    size: int, prev: int | None = None, xref_stream: bool = False,
    flate: bool = False, free: tuple[int, ...] = (), extra: bytes = b"",
) -> bytes:
    """``base`` plus one incremental update section declaring ``objects``.

    ``extra`` is spliced in after the objects and before the xref section
    (for undeclared-object tests). ``free`` marks object numbers deleted.
    """
    prev = last_startxref(base) if prev is None else prev
    out = bytearray(base if base.endswith(b"\n") else base + b"\n")
    offsets: dict[int, int] = {}
    for num, body in objects.items():
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    out += extra
    info_ref = b" /Info %d 0 R" % info if info is not None else b""
    trailer = b"/Size %d /Root %d 0 R%s /Prev %d" % (size, root, info_ref, prev)
    at = len(out)
    if xref_stream:
        out += _xref_stream(size - 1, at, offsets, trailer, flate)
    else:
        out += _xref_table(offsets, free) + b"trailer\n<< " + trailer + b" >>\n"
    out += b"startxref\n%d\n%%%%EOF\n" % at
    return bytes(out)


def metadata_only_resave(base: BasePdf, *, xref_stream: bool = True,
                         flate: bool = True) -> bytes:
    """The D042 shape: new Info, new XMP stream, catalog re-pointed at it,
    and (by default) a Flate-compressed xref stream."""
    n = base.size
    objects = {
        n: info_body(),
        n + 1: xmp_body(),
        base.root_num: catalog_body(base, Metadata=n + 1),
    }
    return append_update(base.data, objects, root=base.root_num, info=n,
                         size=n + 3 if xref_stream else n + 2,
                         xref_stream=xref_stream, flate=flate)


def content_changed_resave(base: BasePdf) -> bytes:
    """Same base, but the update replaces the page's ``/Contents`` stream."""
    objects = {base.contents_num: stream_body(b"BT /F1 9 Tf (EDITED) Tj ET")}
    return append_update(base.data, objects, root=base.root_num,
                         info=base.info_num, size=base.size)


def write_pair(tmp_dir, old: bytes, new: bytes):
    """Write ``old``/``new`` under ``tmp_dir``; return the two paths."""
    old_path, new_path = tmp_dir / "old.pdf", tmp_dir / "new.pdf"
    old_path.write_bytes(old)
    new_path.write_bytes(new)
    return old_path, new_path


__all__ = [
    "BasePdf",
    "append_update",
    "build_base_pdf",
    "catalog_body",
    "content_changed_resave",
    "info_body",
    "last_startxref",
    "metadata_only_resave",
    "stream_body",
    "write_pair",
    "xmp_body",
]
