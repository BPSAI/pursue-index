"""Which worklist cards the image r2-mirror stage covers."""

from __future__ import annotations

_NON_IMG_ASSET_TYPES = frozenset({"PDF", "VID", "AUD"})


def select_image_cards(
    card_ids: list[str], manifest_cards: list[dict]
) -> tuple[list[str], dict[str, str]]:
    """Split a worklist into IMG cards and reported non-IMG skips.

    Returns ``(in_scope, skipped)``; ``skipped`` maps card_id -> the asset
    types it carries. Fails closed: an id absent from the manifest, or with a
    row lacking ``asset_type``, stays in scope and is gated normally.
    """
    types: dict[str, set[str | None]] = {}
    for card in manifest_cards:
        cid = card.get("card_id")
        if cid:
            types.setdefault(cid, set()).add(card.get("asset_type"))
    in_scope: list[str] = []
    skipped: dict[str, str] = {}
    for cid in card_ids:
        seen = types.get(cid)
        # Fails closed like select_pdf_cards: skip only an id whose every row
        # is a known non-IMG type; unknown or untyped ids stay gated.
        if seen and seen <= _NON_IMG_ASSET_TYPES:
            skipped[cid] = "+".join(sorted(str(t) for t in seen))
        else:
            in_scope.append(cid)
    return in_scope, skipped
