"""Per-entry OG image builder for ``/finds/<slug>`` pages.

Composition is intentionally close to the default site OG card
(:mod:`pursue_index.web.og_image`) — same dark bg, scanlines, corner
brackets, footer, terminal command header, manifest sha line, and red
``DECLASSIFIED`` stamp — so individual entry shares are recognisably
part of the same publication. The differences:

- The ``PURSUE://INDEX_`` lockup is replaced by the entry **title**,
  wrapped across up to 3 lines and truncated with ellipsis if the
  third line still overflows. Single-token titles wider than the
  title box are hard-broken by character so nothing escapes.
- The "DOW PURSUE UAP Document Archive" tagline is replaced by the
  entry's **subtitle** (when present), or the slug breadcrumb
  ``/FINDS/<slug>`` (when not) — ellipsized symmetrically on both
  paths.
- The stat strip is replaced by a small **source label** (e.g.
  ``FBI · 48443212`` — agency + 8-char card_id prefix matching the
  Astro source rail) so the reader's eye lands on what document(s)
  the entry is about.

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

from PIL import Image

from . import finds_og_layers as text_layers
from . import og_layers as layers
from .finds_frontmatter import FindsFrontmatter, parse_finds_frontmatter
from .og_writer import write_deterministic_png

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


# Backward-compatible aliases — tests reference the private names by
# their original identifiers. Re-export the layers-module helpers so
# existing imports keep working without churning the test file.
_wrap_title = text_layers.wrap_title
_truncate_with_ellipsis = text_layers.truncate_with_ellipsis
entry_title = text_layers.entry_title
entry_subtitle = text_layers.entry_subtitle
entry_source_label = text_layers.entry_source_label


def render_finds_og_image(ctx: FindsOgContext, out_path: Path) -> None:
    """Render the per-entry OG image and write it as an optimized PNG.

    Idempotent: writing twice with the same ``ctx`` produces byte-stable
    output (same posture as :func:`og_image.render_og_image`, both call
    through :func:`og_writer.write_deterministic_png`).
    """
    im = Image.new("RGBA", (layers.W, layers.H), layers.BG_DEEP)
    layers.background(im)
    layers.corner_brackets(im)
    layers.header_command(im)
    text_layers.entry_title(im, title=ctx.title)
    text_layers.entry_subtitle(im, subtitle=ctx.subtitle, slug=ctx.slug)
    text_layers.entry_source_label(im, source_label=ctx.source_label)
    layers.manifest_hash_line(im, csv_sha256=ctx.csv_sha256)
    layers.footer_bar(im, status_label=ctx.status_label)
    layers.declassified_stamp(im)
    write_deterministic_png(im, out_path)
