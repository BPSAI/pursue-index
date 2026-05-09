"""Drawing helpers for the OG image — one function per visual layer.

Kept separate from ``og_image.py`` so the orchestrator stays small and
the layers are individually inspectable / swappable. Colors mirror the
site's terminal palette (``web/src/styles/global.css``):

- bg-deep        ``#0a0d12``
- text-bright    ``#ecf2f9``
- text-dim       ``#c5cdd6``
- text-faint     ``#4a5563``
- border         ``#1f2a35``  (footer rule, subtle separators)
- border-bright  ``#2f3d4e``  (corner brackets, declassified-doc trim)
- signal-green   ``#a4ff5a``
- signal-cyan    ``#5fd4ff``
- signal-amber   ``#ffc857``
- declass-red    ``#d4313a``  (used only in the stamp)
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from . import og_fonts as fonts

# Palette
BG_DEEP = (10, 13, 18)
TEXT_BRIGHT = (236, 242, 249)
TEXT_DIM = (197, 205, 214)
TEXT_FAINT = (74, 85, 99)
BORDER = (31, 42, 53)  # #1f2a35 — site --color-border (footer rule)
BORDER_BRIGHT = (47, 61, 78)  # #2f3d4e — site --color-border-bright (corner trim)
SIGNAL_GREEN = (164, 255, 90)
SIGNAL_CYAN = (95, 212, 255)
SIGNAL_AMBER = (255, 200, 87)
DECLASS_RED = (212, 49, 58)

# Geometry
W, H = 1200, 630


def background(im: Image.Image) -> None:
    """Solid deep-bg paint + a faint scanline overlay.

    Scanlines must be painted on a separate transparent overlay and
    alpha-composited in — drawing alpha-tinted lines straight onto the
    base layer with ``ImageDraw`` produced opaque banding (the alpha
    channel got baked, not blended).
    """
    base = ImageDraw.Draw(im)
    base.rectangle((0, 0, W, H), fill=BG_DEEP)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Faint horizontal lines every 4px. Alpha tuned so they read at
    # full size but disappear on Slack/iMessage thumbnails.
    for y in range(0, H, 4):
        od.line(((0, y), (W, y)), fill=(196, 220, 255, 10), width=1)
    im.alpha_composite(overlay)

    # Top accent line — signature signal-green halo.
    base.rectangle((0, 0, W, 2), fill=SIGNAL_GREEN)


def corner_brackets(im: Image.Image) -> None:
    """Declassified-doc corner brackets — four L-shapes inset from edges."""
    draw = ImageDraw.Draw(im)
    inset, length, w = 60, 30, 2
    corners = (
        ((inset, inset + length), (inset, inset), (inset + length, inset)),
        ((W - inset - length, inset), (W - inset, inset), (W - inset, inset + length)),
        ((inset, H - inset - length), (inset, H - inset), (inset + length, H - inset)),
        ((W - inset, H - inset - length), (W - inset, H - inset), (W - inset - length, H - inset)),
    )
    for poly in corners:
        draw.line(poly, fill=BORDER_BRIGHT, width=w)


def header_command(im: Image.Image) -> None:
    """Top line — fake terminal command, e.g. ``$ cat /etc/pursue/release.manifest``."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(22)
    draw.text((100, 110), "$ ", font=f, fill=TEXT_FAINT)
    draw.text((128, 110), "cat /etc/pursue/release.manifest", font=f, fill=SIGNAL_GREEN)


def lockup(im: Image.Image) -> None:
    """The PURSUE://INDEX wordmark + blinking caret bar.

    Drawn in three colored runs so ``://`` lights up green like the
    site header, and the trailing caret block sits flush with the
    cap-height of ``X``.
    """
    draw = ImageDraw.Draw(im)
    f = fonts.mono(96, bold=True)
    x, y = 100, 200
    # "PURSUE"
    draw.text((x, y), "PURSUE", font=f, fill=(107, 119, 131))
    pursue_w = draw.textlength("PURSUE", font=f)
    # "://"
    sep_x = x + pursue_w
    draw.text((sep_x, y), "://", font=f, fill=SIGNAL_GREEN)
    sep_w = draw.textlength("://", font=f)
    # "INDEX"
    idx_x = sep_x + sep_w
    draw.text((idx_x, y), "INDEX", font=f, fill=TEXT_BRIGHT)
    idx_w = draw.textlength("INDEX", font=f)
    # Caret bar — sized to a single cell of the monospace font, placed
    # just to the right of "INDEX" with ~6 px breathing room.
    caret_x = idx_x + idx_w + 6
    cell_w = int(draw.textlength("X", font=f))
    draw.rectangle((caret_x, y + 12, caret_x + cell_w, y + 90), fill=SIGNAL_GREEN)


def tagline(im: Image.Image) -> None:
    draw = ImageDraw.Draw(im)
    f = fonts.sans(30)
    draw.text((100, 320), "DOW PURSUE UAP Document Archive", font=f, fill=TEXT_DIM)


def stat_strip(im: Image.Image, *, cards: int, pages: int, source_host: str) -> None:
    """Provenance line: card count, page count, source host.

    Mirrors the footer-stat aesthetic from ``Base.astro``: dim labels,
    bright counts, signal-cyan highlight on the page total to draw the
    eye to the most "scale" number.
    """
    draw = ImageDraw.Draw(im)
    f = fonts.mono(22)

    parts: list[tuple[str, tuple[int, int, int]]] = [
        ("N ", TEXT_FAINT),
        (f"{cards}", TEXT_BRIGHT),
        ("  CARDS  ·  PAGES ", TEXT_FAINT),
        (f"{pages:,}", SIGNAL_CYAN),
        ("  ·  SRC ", TEXT_FAINT),
        (source_host, TEXT_BRIGHT),
    ]
    x = 100
    y = 400
    for text, color in parts:
        draw.text((x, y), text, font=f, fill=color)
        x += int(draw.textlength(text, font=f))


def manifest_hash_line(im: Image.Image, *, csv_sha256: str) -> None:
    """Lower-text manifest hash — the "cite-able" pointer."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(18)
    short = csv_sha256[:16]
    draw.text((100, 445), "sha256 ", font=f, fill=TEXT_FAINT)
    label_w = int(draw.textlength("sha256 ", font=f))
    draw.text((100 + label_w, 445), f"{short}…", font=f, fill=TEXT_DIM)


def footer_bar(im: Image.Image, *, status_label: str) -> None:
    """Bottom rule + status pill + brand."""
    draw = ImageDraw.Draw(im)
    draw.line(((100, 510), (1100, 510)), fill=BORDER, width=1)
    f = fonts.mono(20)
    draw.text((100, 540), "STATUS ", font=f, fill=TEXT_FAINT)
    sw = int(draw.textlength("STATUS ", font=f))
    draw.text((100 + sw, 540), status_label, font=f, fill=SIGNAL_AMBER)
    # Right-aligned brand
    brand = "© BPS AI SOFTWARE"
    bw = int(draw.textlength(brand, font=f))
    draw.text((1100 - bw, 540), brand, font=f, fill=TEXT_DIM)


def declassified_stamp(im: Image.Image) -> None:
    """Angled red ``DECLASSIFIED`` stamp pasted on top of the lockup.

    Drawn into a separate transparent canvas so it can be rotated
    without antialiasing the bg. Slightly translucent so it reads as
    a stamp, not a solid label.
    """
    stamp_w, stamp_h = 520, 140
    canvas = Image.new("RGBA", (stamp_w, stamp_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(canvas)
    border_w = 6
    cd.rectangle((0, 0, stamp_w - 1, stamp_h - 1), outline=DECLASS_RED, width=border_w)
    cd.rectangle(
        (border_w + 6, border_w + 6, stamp_w - border_w - 7, stamp_h - border_w - 7),
        outline=DECLASS_RED,
        width=2,
    )
    f = fonts.mono(64, bold=True)
    text = "DECLASSIFIED"
    tw = int(cd.textlength(text, font=f))
    cd.text(((stamp_w - tw) // 2, (stamp_h - 76) // 2), text, font=f, fill=DECLASS_RED)
    rotated = canvas.rotate(-12, resample=Image.BICUBIC, expand=True)
    # Knock the alpha down so it reads as ink-on-paper, not a sticker.
    alpha = rotated.split()[-1].point(lambda a: int(a * 0.78))
    rotated.putalpha(alpha)
    # Position in upper-right quadrant, partly overlapping the lockup.
    im.alpha_composite(rotated, (640, 60))
