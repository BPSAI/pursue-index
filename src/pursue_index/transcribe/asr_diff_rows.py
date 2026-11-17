"""AUD row logic shared by the ``asr-diff run`` preview and the ``asr-diff live`` plan.

Both commands walk the same rows and must agree on them, so the card
selection and the row duration live here once.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.card_id import require_card_ids
from pursue_index.scrape import load_manifest


def aud_card_ids(manifest_path: Path, cards_filter: str | None) -> list[str]:
    """The manifest's AUD card_ids, in manifest order, narrowed to the
    comma-separated ``cards_filter`` when given. A malformed card_id in the
    filter raises ``InvalidCardIdError``."""
    wanted = (
        set(require_card_ids(c.strip() for c in cards_filter.split(",") if c.strip()))
        if cards_filter else None
    )
    aud_cards = [c.card_id for c in load_manifest(manifest_path).cards if c.asset_type == "AUD"]
    if wanted is not None:
        aud_cards = [c for c in aud_cards if c in wanted]
    return aud_cards


def row_duration(meta: dict, row: dict) -> float:
    """A row's audio seconds: its own ``audio_duration_s``, else the top-level
    ``meta.audio_duration_s`` for single-row meta only (older single-row meta
    keeps it there; a multi-row card's total is not any one row's). Missing,
    unreadable or negative reads as 0."""
    value = row.get("audio_duration_s")
    if value is None and len(meta.get("rows") or []) <= 1:
        value = meta.get("audio_duration_s")
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
