"""By-card links that let the transcribe stage find a staged A/V download.

The A/V bytes are staged under their DOD-id name; the transcribe stage looks
a card up by ``card_id``, so each staged file also gets a link under
``by-card/``. Split out of ``fetch`` to keep that module to the fetch flow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pursue_index.transcribe.eligibility import CARD_LINK_DIR, row_keys_for


def create_card_link(dod_path: Path, card_id: str, row_key: str = "") -> None:
    """Link ``<staging>/by-card/<card_id>[-<row_key>].mp4`` to ``dod_path``.

    The link stays out of the staging dir's top level, which the DOD-id
    matcher globs. A row of a multi-row card carries its row key, so rows
    never share a name.
    """
    link_dir = dod_path.parent / CARD_LINK_DIR
    link_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{card_id}-{row_key}" if row_key else card_id
    link_path = link_dir / f"{stem}.mp4"
    if link_path.is_symlink() and not link_path.exists():
        link_path.unlink()
    if link_path.exists():
        return
    try:
        os.link(dod_path, link_path)
    except (OSError, NotImplementedError):
        link_path.symlink_to(Path("..") / dod_path.name)


def row_keys_by_position(cards: list[Any]) -> list[str]:
    """A row key per card, assigned within each (card_id, asset_type) group.

    Uses the transcribe stage's rule, so the link a row is staged under is the
    one ``audio_path_for`` looks for: empty for a card with one row, else keyed.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for position, card in enumerate(cards):
        groups.setdefault((card.card_id, card.asset_type), []).append(position)
    keys = [""] * len(cards)
    for positions in groups.values():
        for position, key in zip(positions, row_keys_for([cards[i] for i in positions]), strict=True):
            keys[position] = key
    return keys
