"""The observations index — the list consumers enumerate.

``embed.image_observations.load_observation_text`` reads the card_ids from
``index.json`` and then each card's ``<card_id>.json`` sidecar, so a sidecar
that is on disk but unlisted carries no text into the search payload or the
embed vectors. A run therefore registers each card it commits, which is what
keeps "the stage reports this card covered" and "a reader can retrieve this
card's text" the same statement.

Registration is additive and order-preserving: existing ids keep their place,
new ids append, and every other key of the index is left exactly as it was.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _read_index(index_path: Path) -> dict[str, Any]:
    """The existing index, or a fresh one when there is none to read."""
    if not index_path.exists():
        return {"schema_version": 1, "card_ids": []}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "card_ids": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "card_ids": []}
    return data


def register_cards(index_path: Path, card_ids: Iterable[str]) -> list[str]:
    """List ``card_ids`` in the index at ``index_path``; return the full list.

    Ids already listed keep their position and are not repeated, so calling
    this after every run converges rather than growing. ``card_count`` is
    restated from the list so the two never disagree.
    """
    index = _read_index(index_path)
    listed: list[str] = [str(c) for c in index.get("card_ids", [])]
    seen = set(listed)
    for card_id in card_ids:
        if card_id not in seen:
            listed.append(card_id)
            seen.add(card_id)
    index["card_ids"] = listed
    index["card_count"] = len(listed)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return listed
