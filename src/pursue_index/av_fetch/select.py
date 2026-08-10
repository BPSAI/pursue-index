"""Row selection for the A/V fetch stage — release date + asset type filter.

VID and AUD cards carry ``asset_url=None`` (war.gov never surfaces a direct
link for DVIDS-hosted media), so the tranche worklist never scopes them —
selection is by ``release_date`` + ``asset_type`` instead, mirroring
``scripts/_video_ingest_core.select_av_cards``'s contract. Kept as a small,
duplicated pure filter rather than cross-importing that ``scripts/`` module
into the installable package.
"""

from __future__ import annotations

from typing import Any

# Asset types whose bytes are DVIDS-hosted and so must be fetched by this
# stage rather than the ordinary asset_url download path.
DVIDS_ASSET_TYPES = ("VID", "AUD")


def select_av_rows(
    cards: list[Any],
    release_date: str,
    asset_types: tuple[str, ...] = DVIDS_ASSET_TYPES,
) -> list[Any]:
    """Cards in this release whose bytes come from a DVIDS download."""
    return [
        c for c in cards if c.asset_type in asset_types and c.release_date == release_date
    ]
