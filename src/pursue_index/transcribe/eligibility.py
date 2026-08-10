"""Eligibility selection for the transcribe stage — AUD rows only.

VID is never transcribed: it is radar/FLIR footage with nothing to
transcribe, and DVIDS-hosted VID/AUD both resolve through ``/video/<id>``
(``av_fetch.client``), so the ``asset_type`` field is the only reliable gate.
Selection is row-aware within the manifest: filters by ``asset_type`` per
card, exactly like ``av_fetch.select.select_av_rows``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pursue_index.scrape.types import CardMetadata, Manifest


@dataclass(frozen=True)
class EligibleItem:
    """One AUD card the transcribe stage should process."""

    card_id: str
    title: str
    dvids_video_id: str | None


def select_eligible(
    manifest: Manifest, worklist_ids: set[str] | None
) -> list[EligibleItem]:
    """Eligible AUD items across the manifest, optionally scoped to ``worklist_ids``.

    ``worklist_ids`` of ``None`` is the full-corpus escape hatch (mirrors the
    other heavy stages). Preserves manifest order. VID/PDF/IMG rows are never
    eligible — only ``asset_type == "AUD"``.
    """
    items: list[EligibleItem] = []
    for card in manifest.cards:
        if card.asset_type != "AUD":
            continue
        if worklist_ids is not None and card.card_id not in worklist_ids:
            continue
        items.append(_eligible_item(card))
    return items


def _eligible_item(card: CardMetadata) -> EligibleItem:
    return EligibleItem(
        card_id=card.card_id, title=card.title, dvids_video_id=card.dvids_video_id
    )


def audio_path_for(item: EligibleItem, audio_dir: Path) -> Path:
    """Local mp4 path for ``item``: ``<audio_dir>/<card_id>.mp4``.

    Mirrors the R2 current-pointer naming convention already used for
    ingested A/V bytes (``ingest_release_videos.ingest_one``'s
    ``current_key = f"{card_id}.mp4"``), so an operator can stage the same
    file this stage will later archive under.
    """
    return audio_dir / f"{item.card_id}.mp4"
