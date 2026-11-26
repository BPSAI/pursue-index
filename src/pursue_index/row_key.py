"""The stable key of a manifest row: ``<card_id>#<n>``.

``card_id`` names a source file, and several upstream rows can name one file, so
it cannot tell those rows apart. ``n`` is the 0-based position of the row among
the rows sharing its ``card_id``, in manifest order; a unique ``card_id`` is
``#0``. Every provenance writer takes its keys from here, so they agree.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

__all__ = ["row_keys"]


def row_keys(cards: Sequence[dict[str, Any]]) -> list[str]:
    """One key per manifest row, in manifest order."""
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for card in cards:
        card_id = str(card.get("card_id") or "")
        keys.append(f"{card_id}#{seen[card_id]}")
        seen[card_id] += 1
    return keys
