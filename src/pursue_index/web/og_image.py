"""Build the social-share OG image for pursueindex.com.

Composition: "stamped declassified document" — dark deep-bg, monospace
``PURSUE://INDEX_`` lockup with a blinking-caret bar, faint scanline
overlay, an angled red ``DECLASSIFIED`` stamp in the upper-right, and a
provenance footer line carrying the corpus stats + manifest sha.

Public API:

- ``OgImageContext``: dataclass describing the inputs (card count, page
  total, manifest hash, etc.). Keeping this an explicit value object
  makes the ``test_render_is_byte_stable`` guarantee load-bearing —
  same context => same bytes.
- ``render_og_image(ctx, out_path)``: render and write the PNG.

Output is 1200x630 PNG, < 200 KB. Drop at ``web/public/og.png``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, PngImagePlugin

from . import og_layers as layers


@dataclass(frozen=True)
class OgImageContext:
    """Inputs that affect what the rendered image *says*.

    All fields have to be in here for the byte-stability guarantee — if
    any of them change, the bytes will change; if they don't, the bytes
    won't (modulo Pillow / font version). Pure value object — no hidden
    state.
    """

    cards: int
    pages: int
    csv_sha256: str
    source_host: str = "war.gov"
    status_label: str = "RESEARCH PREVIEW"


def render_og_image(ctx: OgImageContext, out_path: Path) -> None:
    """Render the OG image and write it as an optimized PNG.

    Idempotent: writing twice with the same ``ctx`` produces byte-stable
    output. We strip PIL's default ``pnginfo`` (no timestamps, no text
    chunks) and force ``optimize=True`` + a fixed compression level so
    the encoder doesn't introduce non-determinism.
    """
    im = Image.new("RGBA", (layers.W, layers.H), layers.BG_DEEP)
    layers.background(im)
    layers.corner_brackets(im)
    layers.header_command(im)
    layers.lockup(im)
    layers.tagline(im)
    layers.stat_strip(
        im,
        cards=ctx.cards,
        pages=ctx.pages,
        source_host=ctx.source_host,
    )
    layers.manifest_hash_line(im, csv_sha256=ctx.csv_sha256)
    layers.footer_bar(im, status_label=ctx.status_label)
    layers.declassified_stamp(im)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat = im.convert("RGB")  # PNG with no alpha — smaller, no halo on Slack/iMessage.
    pnginfo = PngImagePlugin.PngInfo()  # empty => no timestamps, deterministic
    flat.save(
        out_path,
        format="PNG",
        optimize=True,
        compress_level=9,
        pnginfo=pnginfo,
    )
