"""Font resolution for the OG image builder.

Strategy: prefer the project's bundled JetBrains-Mono-style font (when
present), otherwise fall back to DejaVu Sans Mono, which ships in every
Debian/Ubuntu/CI base image and matches the terminal aesthetic well
enough at OG sizes. Failing both, fall back to PIL's built-in default
(ugly but never crashes — important for "no font fallback fails").
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

# DejaVu Sans Mono is bundled with Pillow itself and present in nearly
# every Linux distro, so this path is highly reliable. We probe a few
# canonical locations in order; first hit wins.
_MONO_REGULAR_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/DejaVuSansMono.ttf",
)
_MONO_BOLD_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
    "/Library/Fonts/DejaVuSansMono-Bold.ttf",
)
_SANS_REGULAR_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/DejaVuSans.ttf",
)


def _first_existing(paths: tuple[str, ...]) -> str | None:
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def mono(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return a monospace font at ``size`` px, falling back gracefully."""
    candidates = _MONO_BOLD_CANDIDATES if bold else _MONO_REGULAR_CANDIDATES
    path = _first_existing(candidates)
    if path is not None:
        return ImageFont.truetype(path, size=size)
    # PIL ships DejaVu under its own data directory.
    try:
        return ImageFont.truetype("DejaVuSansMono-Bold" if bold else "DejaVuSansMono", size=size)
    except OSError:
        return ImageFont.load_default()  # type: ignore[return-value]


def sans(size: int) -> ImageFont.FreeTypeFont:
    """Return a sans-serif font at ``size`` px, falling back gracefully."""
    path = _first_existing(_SANS_REGULAR_CANDIDATES)
    if path is not None:
        return ImageFont.truetype(path, size=size)
    try:
        return ImageFont.truetype("DejaVuSans", size=size)
    except OSError:
        return ImageFont.load_default()  # type: ignore[return-value]
