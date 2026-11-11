"""Mutation operators and case generation for the classifier fuzz harness
(``pursue_index.classify_fuzz``).

``BENIGN_OPS`` touch only document metadata (Info, XMP, leaves they own);
``CONTENT_OPS`` change what a page shows or reads. ``generate_case`` mixes
them, at most one Info and one XMP operator per case.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from pursue_index.classify_fuzz_base import (
    XMP_TEMPLATE,
    Layout,
    Update,
    append,
    build_base,
    catalog_with_metadata,
    image_bytes,
    stream,
    text_ops,
    xmp_body,
)

__all__ = ["BENIGN_OPS", "CONTENT_OPS", "Case", "generate_case"]

Op = Callable[[random.Random, Layout, Update], None]


def _op_info_new(rng: random.Random, layout: Layout, u: Update) -> None:
    u.info = u.fresh()
    u.objects[u.info] = b"<< /Title (fuzz %d) /Producer (resave) >>" % rng.randrange(10_000)


def _op_info_rewrite(rng: random.Random, layout: Layout, u: Update) -> None:
    u.objects[layout.info] = b"<< /Title (fuzz base) /ModDate (D:2024%04d) >>" % rng.randrange(10_000)


def _op_info_leaf(rng: random.Random, layout: Layout, u: Update) -> None:
    leaf = u.fresh()
    u.info = u.fresh()
    u.objects[leaf] = b"(title %d)" % rng.randrange(10_000)
    u.objects[u.info] = b"<< /Title %d 0 R /Producer (resave) >>" % leaf


def _op_xmp_new(rng: random.Random, layout: Layout, u: Update) -> None:
    xmp = u.fresh()
    u.objects[xmp] = xmp_body(rng)
    u.objects[layout.root] = catalog_with_metadata(layout, xmp)


def _op_xmp_rewrite(rng: random.Random, layout: Layout, u: Update) -> None:
    u.objects[layout.xmp] = xmp_body(rng)


def _op_xmp_length_leaf(rng: random.Random, layout: Layout, u: Update) -> None:
    data = XMP_TEMPLATE % b"2025-%02d-01" % rng.randint(1, 12)
    leaf = u.fresh()
    u.objects[leaf] = b"%d" % len(data)
    u.objects[layout.xmp] = (b"<< /Type /Metadata /Subtype /XML /Length %d 0 R >>\nstream\n" % leaf
                             + data + b"\nendstream")


def _op_content(rng: random.Random, layout: Layout, u: Update) -> None:
    u.objects[rng.choice(layout.contents)] = stream(text_ops(rng) + b" 0 0 10 10 re f")


def _op_content_as_xmp(rng: random.Random, layout: Layout, u: Update) -> None:
    u.objects[rng.choice(layout.contents)] = stream(
        b"BT /F1 12 Tf 20 20 Td (retyped) Tj ET", b"/Type /Metadata /Subtype /XML")


def _op_image(rng: random.Random, layout: Layout, u: Update) -> None:
    u.objects[rng.choice(layout.images)] = stream(
        bytes(255 - b for b in image_bytes(rng)),
        b"/Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8")


def _op_appearance(rng: random.Random, layout: Layout, u: Update) -> None:
    if not layout.appearances:
        return _op_content(rng, layout, u)
    u.objects[rng.choice(layout.appearances)] = stream(
        b"1 0 0 rg 0 0 20 20 re f", b"/Type /XObject /Subtype /Form /BBox [0 0 20 20]")
    return None


def _op_page_rotate(rng: random.Random, layout: Layout, u: Update) -> None:
    i = rng.randrange(len(layout.pages))
    body = layout.objects[layout.pages[i]]
    if layout.dangling is not None:
        body = body.replace(b" /Rotate %d 0 R" % layout.dangling, b"")
    u.objects[layout.pages[i]] = body[:-2] + b" /Rotate 90 >>"


def _op_dangling_define(rng: random.Random, layout: Layout, u: Update) -> None:
    """Define the number an old page's ``/Rotate`` names, owned by a new Info."""
    if layout.dangling is None:
        return _op_page_rotate(rng, layout, u)
    u.next_num = max(u.next_num, layout.dangling + 1)
    u.objects[layout.dangling] = b"90"
    u.info = u.fresh()
    u.objects[u.info] = b"<< /Title (fuzz) /Subject %d 0 R >>" % layout.dangling
    return None


def _op_resources(rng: random.Random, layout: Layout, u: Update) -> None:
    i = rng.randrange(len(layout.pages))
    body = layout.objects[layout.pages[i]]
    u.objects[layout.pages[i]] = body.replace(b"/Im0 %d 0 R" % layout.images[i],
                                              b"/Im0 %d 0 R" % layout.images[-1 - i])
    if len(layout.images) == 1:
        _op_image(rng, layout, u)


BENIGN_OPS: dict[str, Op] = {
    "info-new": _op_info_new,
    "info-rewrite": _op_info_rewrite,
    "info-leaf": _op_info_leaf,
    "xmp-new": _op_xmp_new,
    "xmp-rewrite": _op_xmp_rewrite,
    "xmp-length-leaf": _op_xmp_length_leaf,
}
CONTENT_OPS: dict[str, Op] = {
    "content": _op_content,
    "content-as-xmp": _op_content_as_xmp,
    "image": _op_image,
    "appearance": _op_appearance,
    "page-rotate": _op_page_rotate,
    "dangling-define": _op_dangling_define,
    "resources": _op_resources,
}


@dataclass(frozen=True)
class Case:
    index: int
    ops: tuple[str, ...]
    old: bytes
    new: bytes


def generate_case(rng: random.Random, index: int = 0) -> Case:
    """One pair: 1-3 operators, about half of the cases metadata-only."""
    old, layout = build_base(rng)
    pool = dict(BENIGN_OPS)
    if rng.random() < 0.5:
        pool.update(CONTENT_OPS)
    names = sorted(pool)
    # At most one operator per family: a second Info or XMP edit would orphan
    # the first, which the classifier rightly refuses (noise, not signal).
    chosen: list[str] = []
    for name in (rng.choice(names) for _ in range(rng.randint(1, 3))):
        family = name.split("-")[0]
        if family in ("info", "xmp") and any(c.split("-")[0] == family for c in chosen):
            continue
        if name not in chosen:
            chosen.append(name)
    update = Update(next_num=layout.size)
    for name in chosen:
        pool[name](rng, layout, update)
    return Case(index, tuple(chosen), old, append(old, layout, update, rng))


