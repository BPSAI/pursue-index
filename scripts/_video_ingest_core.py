"""Pure, network-free logic for release video/audio ingest.

Extracted from the ingest orchestrator so the card-selection and
file-matching rules are unit-testable without a DVIDS round-trip or an
arch-check size violation on the entrypoint script.

The DOD-id indirection (why matching is by numeric id, not filename):
the manifest card carries a ``dvids_video_id`` (e.g. ``1010263``); the
operator's downloaded file is named for the *DOD asset id* (e.g.
``DOD_111764142-1920x1080-9000k.mp4``). These are different numbers. The
only bridge is the public DVIDS page, which references the bare
``DOD_<id>.mp4``. Operator downloads, however, carry a resolution/bitrate
suffix (``-1920x1080-9000k``), so an ``endswith("DOD_<id>.mp4")`` match
fails — we match on the extracted numeric DOD id instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

# DOD asset id as it appears in both the DVIDS page body and the operator's
# downloaded filename. 8-12 digits, optionally followed by a resolution suffix.
_DOD_ID_RE = re.compile(r"DOD_(\d{8,12})")

# Asset types whose bytes are DVIDS-hosted (null asset_url on the card) and so
# must be ingested from operator-downloaded local files rather than fetched.
DVIDS_ASSET_TYPES = ("VID", "AUD")


def dod_id(name: str | None) -> str | None:
    """Extract the numeric DOD asset id from a filename or page reference.

    Handles bare ``DOD_<id>.mp4`` (DVIDS page) and the operator's
    resolution-suffixed ``DOD_<id>-1920x1080-9000k.mp4`` alike.
    """
    if not name:
        return None
    m = _DOD_ID_RE.search(name)
    return m.group(1) if m else None


def select_av_cards(
    cards: list[Any],
    release_date: str,
    asset_types: tuple[str, ...] = DVIDS_ASSET_TYPES,
) -> list[Any]:
    """Cards in this release whose bytes come from a DVIDS download.

    Generalizes the old VID-only filter to include AUD (audio cards are
    also DVIDS-hosted .mp4s with null asset_url).
    """
    return [
        c
        for c in cards
        if c.asset_type in asset_types and c.release_date == release_date
    ]


def match_cards_to_files(
    cards: list[Any],
    desktop_files: list[Path],
    dod_resolver: Callable[[Any], str | None],
) -> tuple[dict[str, tuple[Any, Path]], list[str], list[Path]]:
    """Map cards to operator-downloaded files by DOD numeric id.

    ``dod_resolver(card) -> "DOD_<id>.mp4" | None`` resolves a card's
    ``dvids_video_id`` to its DOD asset filename (network scrape in
    production; injected for tests).

    Returns ``(matched, unmatched_card_ids, unmatched_files)`` where
    ``matched`` is ``card_id -> (card, local_path)``.
    """
    files_by_id: dict[str, Path] = {}
    for p in desktop_files:
        fid = dod_id(p.name)
        if fid is not None:
            files_by_id.setdefault(fid, p)

    matched: dict[str, tuple[Any, Path]] = {}
    unmatched_cards: list[str] = []
    used_ids: set[str] = set()

    for card in cards:
        if not card.dvids_video_id:
            unmatched_cards.append(card.card_id)
            continue
        resolved_id = dod_id(dod_resolver(card))
        if resolved_id is None or resolved_id not in files_by_id:
            unmatched_cards.append(card.card_id)
            continue
        matched[card.card_id] = (card, files_by_id[resolved_id])
        used_ids.add(resolved_id)

    unmatched_files = [p for fid, p in files_by_id.items() if fid not in used_ids]
    return matched, unmatched_cards, unmatched_files
