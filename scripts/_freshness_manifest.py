"""Manifest reading for ``check_ocr_input_freshness.py``: card ids, PDF-ness, release date."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pursue_index.card_id import InvalidCardIdError, require_card_id


class FreshnessError(Exception):
    """An input the gate needs is missing or unreadable, so the run cannot pass."""


def _release_date(raw: object) -> date | None:
    """The manifest's ``M/D/YYYY`` release date, or None when absent or unparseable."""
    try:
        return datetime.strptime(str(raw).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _manifest_cards(manifest: Path) -> list[tuple[str, bool, date | None]]:
    """``(card_id, is_pdf_card, earliest PDF release_date)`` per manifest card, ids validated."""
    try:
        cards = json.loads(manifest.read_text(encoding="utf-8")).get("cards")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise FreshnessError(f"cannot read manifest {manifest}: {exc}") from exc
    if not isinstance(cards, list):
        raise FreshnessError(f"manifest {manifest} has no 'cards' list")
    out: dict[str, tuple[bool, date | None]] = {}
    for card in cards:
        if not isinstance(card, dict) or not card.get("card_id"):
            continue
        try:
            card_id = require_card_id(card["card_id"])
        except InvalidCardIdError as exc:
            raise FreshnessError(f"manifest {manifest}: {exc}") from exc
        is_pdf = str(card.get("asset_type", "")).upper() == "PDF"
        was_pdf, released = out.get(card_id, (False, None))
        if is_pdf:
            when = _release_date(card.get("release_date"))
            released = min(filter(None, (released, when)), default=None)
        out[card_id] = (was_pdf or is_pdf, released)
    return sorted((cid, pdf, rel) for cid, (pdf, rel) in out.items())
