"""Text safety for upstream-derived strings that end up in public posts.

Low-level on purpose: any layer may import it (``scrape``, ``tranche_ready``).
"""

from __future__ import annotations

__all__ = ["neutralize"]

_STRIP: dict[int, str | None] = {ord(c): None for c in "`<>"}
_STRIP[ord("@")] = "＠"
_STRIP.update({c: " " for c in [*range(32), 127] if c not in (9, 10)})


def neutralize(text: str) -> str:
    """No backticks or angle brackets; ``@`` becomes its fullwidth form (U+FF20); no controls."""
    return text.translate(_STRIP)
