"""Text-composition layers for the per-entry finds OG image.

Split out of :mod:`pursue_index.web.finds_og` so the orchestrator
stays small and the layers (title wrap/truncate, subtitle ellipsis,
source label) are individually testable. Mirrors the
``og_image.py`` / ``og_layers.py`` split.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from . import og_fonts as fonts
from . import og_layers as layers

# Title block geometry. The default OG image puts the lockup at y=200
# rendered at 96px; we put the (smaller) title block at the same y so
# the visual centre of gravity matches.
TITLE_X = 100
TITLE_Y = 200
TITLE_MAX_W = 940  # leaves the upper-right quadrant for the stamp
TITLE_LINE_H = 56  # baseline-to-baseline at 44px


def hard_break_long_token(
    token: str,
    *,
    draw: ImageDraw.ImageDraw,
    font: object,
    max_width: int,
) -> list[str]:
    """Break a single un-spaced token by character so each chunk fits.

    A long URL, hash, or chemical name with no whitespace would
    otherwise render past the right margin and through the corner
    brackets / DECLASSIFIED stamp on the public OG card. We split by
    character and pack greedily.
    """
    if draw.textlength(token, font=font) <= max_width:
        return [token]
    chunks: list[str] = []
    cur = ""
    for ch in token:
        candidate = cur + ch
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            if cur:
                chunks.append(cur)
            cur = ch
    if cur:
        chunks.append(cur)
    return chunks


def wrap_title(
    text: str,
    *,
    draw: ImageDraw.ImageDraw,
    font: object,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Greedy word-wrap to ``max_width``; truncate with ellipsis if needed.

    Single tokens wider than ``max_width`` are hard-broken by character
    BEFORE the greedy wrap pass, so a long URL/hash never escapes the
    title box. Real finds-entry titles wrap cleanly at 2-3 lines.
    """
    words = text.split()
    if not words:
        return [""]
    pieces: list[str] = []
    for w in words:
        pieces.extend(
            hard_break_long_token(w, draw=draw, font=font, max_width=max_width)
        )
    lines: list[str] = []
    cur = pieces[0]
    for w in pieces[1:]:
        candidate = f"{cur} {w}"
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) <= max_lines:
        return lines
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


def truncate_with_ellipsis(
    text: str,
    *,
    draw: ImageDraw.ImageDraw,
    font: object,
    max_width: int,
    original: str,
) -> str:
    """Shorten ``text`` to fit ``max_width`` and append ``…`` if it changed.

    Symmetric across real subtitles AND the slug-breadcrumb fallback —
    a long ``/FINDS/<slug>`` no longer renders without the trailing ``…``.
    """
    out = text
    while out and draw.textlength(out + "…", font=font) > max_width:
        parts = out.rsplit(" ", 1)
        out = parts[0] if len(parts) > 1 else out[:-1]
    if len(out) < len(original):
        out = out + "…"
    return out


def entry_title(im: Image.Image, *, title: str) -> None:
    """Wrap and render the entry title in bright text, up to 3 lines."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(44, bold=True)
    wrapped = wrap_title(
        title, draw=draw, font=f, max_width=TITLE_MAX_W, max_lines=3
    )
    for i, line in enumerate(wrapped):
        draw.text(
            (TITLE_X, TITLE_Y + i * TITLE_LINE_H),
            line,
            font=f,
            fill=layers.TEXT_BRIGHT,
        )


def entry_subtitle(im: Image.Image, *, subtitle: str | None, slug: str) -> None:
    """Render the subtitle (or ``/FINDS/<slug>`` fallback) below the title.

    Subtitles can be long; we truncate to fit one line so they read as
    a single tagline rather than wrapping into the stat row. The
    ellipsis is applied symmetrically to both the real-subtitle and
    fallback paths so a long slug fallback never silently hides the
    truncation.
    """
    draw = ImageDraw.Draw(im)
    f = fonts.sans(24)
    original = subtitle if subtitle else f"/FINDS/{slug}"
    text = truncate_with_ellipsis(
        original, draw=draw, font=f, max_width=TITLE_MAX_W, original=original
    )
    draw.text((TITLE_X, 380), text, font=f, fill=layers.TEXT_DIM)


def entry_source_label(im: Image.Image, *, source_label: str) -> None:
    """Render the source-card breadcrumb (e.g. ``FBI · 4844321219``)."""
    draw = ImageDraw.Draw(im)
    f = fonts.mono(20)
    draw.text((TITLE_X, 422), "SRC ", font=f, fill=layers.TEXT_FAINT)
    label_w = int(draw.textlength("SRC ", font=f))
    draw.text(
        (TITLE_X + label_w, 422),
        source_label,
        font=f,
        fill=layers.SIGNAL_CYAN,
    )
