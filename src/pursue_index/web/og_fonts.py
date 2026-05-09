"""Font resolution for the OG image builder.

Strategy: prefer the project's bundled JetBrains-Mono-style font (when
present), otherwise fall back to DejaVu Sans Mono, which ships in every
Debian/Ubuntu/CI base image and matches the terminal aesthetic well
enough at OG sizes. Failing both, raise ``FontLoadError`` — silently
falling back to ``ImageFont.load_default()`` is a trap because that
function ignores the requested ``size`` and returns Pillow's bundled
font at its own ~10–13px, which would collapse the 96px lockup and
ship an unreadable og.png. We'd rather fail loudly at build time.
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


class FontLoadError(RuntimeError):
    """Raised when no real TTF font can be resolved for the requested face.

    We deliberately do not fall back to ``ImageFont.load_default()``
    because that function ignores the requested ``size`` parameter and
    returns Pillow's bundled font at its own native size (~10–13px).
    A 96px lockup rendered at 10px would silently produce an
    unreadable og.png — better to fail the build.
    """


def _first_existing(paths: tuple[str, ...]) -> str | None:
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def mono(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return a monospace font at ``size`` px or raise ``FontLoadError``."""
    candidates = _MONO_BOLD_CANDIDATES if bold else _MONO_REGULAR_CANDIDATES
    path = _first_existing(candidates)
    if path is not None:
        return ImageFont.truetype(path, size=size)
    # PIL ships DejaVu under its own data directory.
    try:
        return ImageFont.truetype("DejaVuSansMono-Bold" if bold else "DejaVuSansMono", size=size)
    except OSError as exc:
        face = "DejaVuSansMono-Bold" if bold else "DejaVuSansMono"
        raise FontLoadError(
            f"could not resolve a real TTF for {face!r} at size={size}px; "
            f"checked {candidates} and Pillow's bundled font directory. "
            "Install fonts-dejavu (Debian/Ubuntu) or equivalent."
        ) from exc


def sans(size: int) -> ImageFont.FreeTypeFont:
    """Return a sans-serif font at ``size`` px or raise ``FontLoadError``."""
    path = _first_existing(_SANS_REGULAR_CANDIDATES)
    if path is not None:
        return ImageFont.truetype(path, size=size)
    try:
        return ImageFont.truetype("DejaVuSans", size=size)
    except OSError as exc:
        raise FontLoadError(
            f"could not resolve a real TTF for 'DejaVuSans' at size={size}px; "
            f"checked {_SANS_REGULAR_CANDIDATES} and Pillow's bundled font "
            "directory. Install fonts-dejavu (Debian/Ubuntu) or equivalent."
        ) from exc
