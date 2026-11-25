"""The file-type change warning: one detection, run on every lane whatever its flags."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

from _r2_hosts import type_change_line

from pursue_index.asset_rows import type_change


def type_change_with_asset_gone(
    rows: list[dict[str, Any]] | None, asset_url: Any, asset_filename: Any, current_urls: Collection[str]
):
    """The one 'asset gone' predicate: ``type_change``'s ``(previous_row, old, new)`` when the card
    has no rows for this URL, its file type changed with it, and its previous asset's URL is no
    longer among the card's manifest URLs; otherwise ``None``."""
    found = type_change(rows, asset_url, asset_filename)
    if found and str(found[0].get("asset_url")) not in current_urls:
        return found
    return None


def warn_type_changes(registry: dict[str, list[dict[str, Any]]], manifest_cards: Iterable[Any], eligible=None) -> int:
    """Print one ``TYPE CHANGE`` line per card asset (of ``eligible``, default all) whose type
    changed along with its URL. Not a drift gate, so no window applies. Returns the count."""
    cards = list(manifest_cards)
    urls: dict[str, set[str]] = {}
    for card in cards:
        urls.setdefault(card.card_id, set()).add(str(card.asset_url))
    count = 0
    for card in cards if eligible is None else eligible:
        found = type_change_with_asset_gone(
            registry.get(card.card_id), card.asset_url, card.asset_filename, urls[card.card_id]
        )
        if found:
            print(type_change_line(card.card_id, *found, card.asset_url))
            count += 1
    return count
