"""Base documents and incremental updates for the classifier fuzz harness
(``pursue_index.classify_fuzz``).

``build_base`` writes a small PDF by hand (classic xref table) so the harness
controls every object number, including a page ``/Rotate`` that names an
object the file never defines. ``append`` adds one incremental update with
either a classic xref table or an xref stream (Flate or not).
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass, field

__all__ = ["XMP_TEMPLATE", "Layout", "Update", "append", "build_base", "image_bytes", "stream", "text_ops"]

XMP_TEMPLATE = (
    b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    b"<xmp:ModifyDate>%s</xmp:ModifyDate></rdf:Description></rdf:RDF></x:xmpmeta>"
    b'<?xpacket end="w"?>'
)
_WORDS = ("alpha", "bravo", "delta", "echo", "golf", "kilo", "lima", "oscar", "tango", "zulu")


# --------------------------------------------------------------------------
# Base document
# --------------------------------------------------------------------------


@dataclass
class Layout:
    """Object numbers of a generated base document."""

    root: int
    info: int
    xmp: int
    pages: list[int]
    contents: list[int]
    images: list[int]
    annots: list[int]
    appearances: list[int]
    dangling: int | None
    size: int
    objects: dict[int, bytes] = field(default_factory=dict)


def stream(data: bytes, entries: bytes = b"") -> bytes:
    return b"<< " + entries + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def text_ops(rng: random.Random) -> bytes:
    words = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(1, 4)))
    x, y = rng.randint(10, 60), rng.randint(20, 140)
    return b"BT /F1 %d Tf %d %d Td (%s) Tj ET" % (rng.randint(8, 14), x, y, words.encode())


def image_bytes(rng: random.Random) -> bytes:
    return bytes(rng.randrange(256) for _ in range(16))


def _serialize(objects: dict[int, bytes], root: int, info: int) -> bytes:
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
    size = max(objects) + 1
    at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for num in range(1, size):
        out += (b"%010d 00000 n \n" % offsets[num]) if num in offsets else b"0000000000 00000 f \n"
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\n" % (size, root, info)
    out += b"startxref\n%d\n%%%%EOF\n" % at
    return bytes(out)


def build_base(rng: random.Random) -> tuple[bytes, Layout]:
    """A 1-3 page document: text, an image, maybe an annotation with an
    appearance stream, Info + XMP, and maybe a page whose ``/Rotate`` names
    an object number the file never defines (it resolves to null)."""
    objects: dict[int, bytes] = {}
    nums = iter(range(1, 10_000))
    root, pages_num, font = next(nums), next(nums), next(nums)
    info, xmp = next(nums), next(nums)
    objects[font] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[info] = b"<< /Title (fuzz base) /Producer (base) >>"
    objects[xmp] = stream(XMP_TEMPLATE % b"2023-01-01", b"/Type /Metadata /Subtype /XML")
    layout = Layout(root, info, xmp, [], [], [], [], [], None, 0)
    dangling_on = rng.randrange(3) if rng.random() < 0.3 else None
    dangling_num = 9000 + rng.randrange(500) if dangling_on is not None else None
    for i in range(rng.randint(1, 3)):
        page, contents, image = next(nums), next(nums), next(nums)
        objects[image] = stream(
            image_bytes(rng),
            b"/Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceGray "
            b"/BitsPerComponent 8",
        )
        ops = b"q 60 0 0 60 100 100 cm /Im0 Do Q " + text_ops(rng)
        objects[contents] = stream(ops)
        extra = b""
        if rng.random() < 0.5:
            annot, ap = next(nums), next(nums)
            objects[ap] = stream(b"0 0 1 rg 0 0 20 20 re f", b"/Type /XObject /Subtype /Form /BBox [0 0 20 20]")
            objects[annot] = (b"<< /Type /Annot /Subtype /Square /Rect [150 150 170 170] "
                              b"/F 4 /AP << /N %d 0 R >> >>" % ap)
            extra += b" /Annots [%d 0 R]" % annot
            layout.annots.append(annot)
            layout.appearances.append(ap)
        if dangling_on == i:
            extra += b" /Rotate %d 0 R" % dangling_num
            layout.dangling = dangling_num
        objects[page] = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 200 160] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> /XObject << /Im0 %d 0 R >> >>%s >>"
            % (pages_num, contents, font, image, extra)
        )
        layout.pages.append(page)
        layout.contents.append(contents)
        layout.images.append(image)
    kids = b" ".join(b"%d 0 R" % p for p in layout.pages)
    objects[pages_num] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(layout.pages))
    objects[root] = b"<< /Type /Catalog /Pages %d 0 R /Metadata %d 0 R >>" % (pages_num, xmp)
    layout.objects = objects
    layout.size = max(objects) + 1
    return _serialize(objects, root, info), layout


# --------------------------------------------------------------------------
# Incremental update
# --------------------------------------------------------------------------


@dataclass
class Update:
    objects: dict[int, bytes] = field(default_factory=dict)
    info: int | None = None
    next_num: int = 0

    def fresh(self) -> int:
        self.next_num += 1
        return self.next_num - 1


def _xref_section(offsets: dict[int, int], trailer: bytes, at: int, num: int | None,
                  flate: bool) -> bytes:
    if num is None:
        out = b"xref\n0 1\n0000000000 65535 f \n"
        for n in sorted(offsets):
            out += b"%d 1\n%010d 00000 n \n" % (n, offsets[n])
        return out + b"trailer\n<< " + trailer + b" >>\n"
    entries = {**offsets, num: at}
    raw = b"".join(b"\x01" + off.to_bytes(4, "big") + b"\x00\x00" for _, off in sorted(entries.items()))
    index = b" ".join(b"%d 1" % n for n in sorted(entries))
    data = zlib.compress(raw) if flate else raw
    filt = b" /Filter /FlateDecode" if flate else b""
    head = (b"<< /Type /XRef /W [1 4 2] /Index [" + index + b"] " + trailer + filt
            + b" /Length %d >>\nstream\n" % len(data))
    return b"%d 0 obj\n" % num + head + data + b"\nendstream\nendobj\n"


def append(base: bytes, layout: Layout, update: Update, rng: random.Random) -> bytes:
    """``base`` plus one incremental update carrying ``update.objects``."""
    prev = int(base.rsplit(b"startxref", 1)[1].split()[0])
    out = bytearray(base)
    offsets = {}
    for num, body in update.objects.items():
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    use_stream = rng.random() < 0.5
    xref_num = update.fresh() if use_stream else None
    size = update.next_num
    info = update.info if update.info is not None else layout.info
    trailer = b"/Size %d /Root %d 0 R /Info %d 0 R /Prev %d" % (size, layout.root, info, prev)
    at = len(out)
    out += _xref_section(offsets, trailer, at, xref_num, flate=rng.random() < 0.5)
    out += b"startxref\n%d\n%%%%EOF\n" % at
    return bytes(out)


def xmp_body(rng: random.Random) -> bytes:
    return stream(XMP_TEMPLATE % b"2024-%02d-01" % rng.randint(1, 12), b"/Type /Metadata /Subtype /XML")


def catalog_with_metadata(layout: Layout, xmp: int) -> bytes:
    pages = layout.objects[layout.root].split(b"/Pages ")[1].split(b" ")[0]
    return b"<< /Type /Catalog /Pages %s 0 R /Metadata %d 0 R >>" % (pages, xmp)
