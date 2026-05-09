"""Per-entry OG image builder for ``/finds/<slug>`` pages.

Composition is intentionally close to the default site OG card
(:mod:`pursue_index.web.og_image`) — same dark bg, scanlines, corner
brackets, footer, terminal command header, manifest sha line, and red
``DECLASSIFIED`` stamp — so individual entry shares are recognisably
part of the same publication. The differences:

- The ``PURSUE://INDEX_`` lockup is replaced by the entry **title**,
  wrapped across up to 3 lines and truncated with ellipsis if the
  third line still overflows.
- The "DOW PURSUE UAP Document Archive" tagline is replaced by the
  entry's **subtitle** (when present), or the slug breadcrumb
  ``/FINDS/<slug>`` (when not).
- The stat strip is replaced by a small **source label** (e.g.
  ``FBI · 4844321219`` — agency + first card_id prefix) so the
  reader's eye lands on what document(s) the entry is about.

The ``manifest_hash_line`` and ``footer_bar`` are reused unchanged
because they are load-bearing for the reproducibility claim.

Public API:

- :class:`FindsOgContext`: dataclass — pure value object so the
  byte-stability guarantee holds (same context => same bytes).
- :func:`render_finds_og_image`: render and write a PNG.
- :func:`parse_finds_frontmatter` / :class:`FindsFrontmatter`:
  re-exported from :mod:`pursue_index.web.finds_frontmatter` so
  callers have one import surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin

from . import og_fonts as fonts
from . import og_layers as layers
from .finds_frontmatter import FindsFrontmatter, parse_finds_frontmatter

__all__ = [
    "FindsFrontmatter",
    "FindsOgContext",
    "parse_finds_frontmatter",
    "render_finds_og_image",
]


@dataclass(frozen=True)
class FindsOgContext:
    """Inputs that affect what the rendered per-entry image *says*.

    Pure value object — same context => same bytes.
    """

    slug: str
    title: str
    subtitle: str | None
    source_label: str
    csv_sha256: str
    status_label: str = "RESEARCH PREVIEW"


# Title block geometry. The default OG image puts the lockup at y=200
# rendered at 96px; we put the (smaller) title block at the same y so
# the visual centre of gravity matches.
_TITLE_X = 100
_TITLE_Y = 200
_TITLE_MAX_W = 940  # leaves the upper-right quadrant for the stamp
_TITLE_LINE_H = 56  # baseline-to-baseline at 44px


def _wrap_title(
    text: str,
    *,
    draw: ImageDraw.ImageDraw,
    font: object,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Greedy word-wrap to ``max_width``; truncate with ellipsis if needed.

    Long single tokens that exceed ``max_width`` are kept whole on their
    own line — Pillow will let them extend past the right margin, but
    that's strictly better than blowing up. In practice all real
    finds-entry titles wrap cleanly at 2-3 lines.
    """
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        candidate = f"{cur} {w}"
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    # Truncate: keep the first (max_lines-1) lines, ellipsize the last.
    kept = lines[: max_lines - 1]
    remainder = " ".join(lines[max_lines - 1 :])
    while remainder and draw.textlength(remainder + "…", font=font) > max_width:
        parts = remainder.rsplit(" ", 1)
        if len(parts) == 1:
            remainder = remainder[:-1]
        else:
            remainder = parts[0]
    kept.append((remainder + "…") if remainder else "…")
    return kept


def entry_title(im: Image.Image, *, title: str) -> None:
    """Wrap and render the entry title in bright text, up to 3 lines."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(44, bold=True)
    wrapped = _wrap_title(
        title, draw=draw, font=f, max_width=_TITLE_MAX_W, max_lines=3
    )
    for i, line in enumerate(wrapped):
        draw.text(
            (_TITLE_X, _TITLE_Y + i * _TITLE_LINE_H),
            line,
            font=f,
            fill=layers.TEXT_BRIGHT,
        )


def entry_subtitle(im: Image.Image, *, subtitle: str | None, slug: str) -> None:
    """Render the subtitle (or ``/FINDS/<slug>`` fallback) below the title.

    Subtitles can be long; we truncate to fit one line so they read as
    a single tagline rather than wrapping into the stat row.
    """
    draw = ImageDraw.Draw(im)
    f = fonts.sans(24)
    text = subtitle if subtitle else f"/FINDS/{slug}"
    while text and draw.textlength(text + "…", font=f) > _TITLE_MAX_W:
        parts = text.rsplit(" ", 1)
        text = parts[0] if len(parts) > 1 else text[:-1]
    if subtitle and len(text) < len(subtitle):
        text = text + "…"
    draw.text((_TITLE_X, 380), text, font=f, fill=layers.TEXT_DIM)


def entry_source_label(im: Image.Image, *, source_label: str) -> None:
    """Render the source-card breadcrumb (e.g. ``FBI · 4844321219``)."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(20)
    draw.text((_TITLE_X, 422), "SRC ", font=f, fill=layers.TEXT_FAINT)
    label_w = int(draw.textlength("SRC ", font=f))
    draw.text(
        (_TITLE_X + label_w, 422),
        source_label,
        font=f,
        fill=layers.SIGNAL_CYAN,
    )


def render_finds_og_image(ctx: FindsOgContext, out_path: Path) -> None:
    """Render the per-entry OG image and write it as an optimized PNG.

    Idempotent: writing twice with the same ``ctx`` produces byte-stable
    output (same posture as :func:`og_image.render_og_image`).
    """
    im = Image.new("RGBA", (layers.W, layers.H), layers.BG_DEEP)
    layers.background(im)
    layers.corner_brackets(im)
    layers.header_command(im)
    entry_title(im, title=ctx.title)
    entry_subtitle(im, subtitle=ctx.subtitle, slug=ctx.slug)
    entry_source_label(im, source_label=ctx.source_label)
    layers.manifest_hash_line(im, csv_sha256=ctx.csv_sha256)
    layers.footer_bar(im, status_label=ctx.status_label)
    layers.declassified_stamp(im)

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
