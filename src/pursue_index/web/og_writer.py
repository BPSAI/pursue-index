"""Shared deterministic PNG-write helper for the OG renderers.

Both :mod:`pursue_index.web.og_image` (default site card) and
:mod:`pursue_index.web.finds_og` (per-entry finds cards) share the
same byte-stability contract: same context => same bytes. The
postlude that achieves that is identical in both renderers — RGBA→RGB
flatten, empty PngInfo, ``optimize=True`` + ``compress_level=9``.

Extracted here so a future Pillow / encoder change only has to be
patched in one place. The ``flatten`` step also drops the alpha
channel before writing, which produces smaller files and avoids
the halo Slack/iMessage thumbnails would otherwise show.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, PngImagePlugin


def write_deterministic_png(im: Image.Image, out_path: Path) -> None:
    """Flatten ``im`` to RGB and write a byte-stable optimized PNG.

    Idempotent: the same input image and path produce identical bytes
    on every run. Strips PIL's default pnginfo (no timestamps, no
    text chunks) and forces a fixed compression level so the encoder
    doesn't introduce non-determinism.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    flat = im.convert("RGB")
    pnginfo = PngImagePlugin.PngInfo()
    flat.save(
        out_path,
        format="PNG",
        optimize=True,
        compress_level=9,
        pnginfo=pnginfo,
    )
