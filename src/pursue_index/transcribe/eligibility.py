"""Eligibility selection for the transcribe stage — AUD rows only.

VID is never transcribed: it is radar/FLIR footage with nothing to
transcribe, and DVIDS-hosted VID/AUD both resolve through ``/video/<id>``
(``av_fetch.client``), so the ``asset_type`` field is the only reliable gate.

Selection is *row-aware*: within a ``card_id``, each backing manifest row is
its own unit of work. A card_id can be backed by more than one row — the
upstream CSV's real shape — so every item carries a ``row_key`` that separates
the rows sharing an id, and one row can never stand in for another's coverage.
This mirrors ``vision.eligibility``, which counts coverage the same way.

Scoping is by ``release_date``, which is what reaches these rows: VID and AUD
cards carry ``asset_url=None``, so a tranche work list — built from rows that
have an asset URL — never names them. ``av_fetch.select.select_av_rows`` scopes
the same rows by the same field.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from pursue_index.scrape.types import CardMetadata, Manifest

CoverageKey = tuple[str, str]


@dataclass(frozen=True)
class EligibleItem:
    """One AUD manifest row the transcribe stage should process.

    ``row_key`` names which of a card_id's rows this item came from, and is
    empty for the ordinary case of a card_id backed by exactly one AUD row.
    """

    card_id: str
    title: str
    dvids_video_id: str | None
    row_key: str = ""

    @property
    def coverage_key(self) -> CoverageKey:
        """The unit coverage is counted in: ``(card_id, row_key)``."""
        return (self.card_id, self.row_key)


def _row_keys(rows: list[CardMetadata]) -> list[str]:
    """A discriminator per row for the rows sharing one card_id.

    A card_id backed by a single AUD row needs no discriminator and gets an
    empty key, which keeps the sidecar and file naming of the ordinary card
    unchanged. Rows that share an id are separated by their DVIDS id, and by
    their position within the group when that does not separate them — so the
    number of coverage keys always equals the number of eligible rows. Keys
    stay filename-safe because they also name the row's source audio file.
    """
    if len(rows) == 1:
        return [""]
    keys: list[str] = []
    seen: set[str] = set()
    for position, row in enumerate(rows, start=1):
        key = row.dvids_video_id or f"row{position}"
        if key in seen:
            key = f"{key}-{position}"
        seen.add(key)
        keys.append(key)
    return keys


def select_eligible(
    manifest: Manifest, release_date: str | None
) -> list[EligibleItem]:
    """Eligible AUD rows across the manifest, optionally scoped to a release.

    ``release_date`` of ``None`` is the full-corpus escape hatch. Preserves
    manifest order. VID/PDF/IMG rows are never eligible — only
    ``asset_type == "AUD"``.
    """
    groups: OrderedDict[str, list[CardMetadata]] = OrderedDict()
    for card in manifest.cards:
        if card.asset_type != "AUD":
            continue
        if release_date is not None and card.release_date != release_date:
            continue
        groups.setdefault(card.card_id, []).append(card)

    items: list[EligibleItem] = []
    for rows in groups.values():
        for card, row_key in zip(rows, _row_keys(rows), strict=True):
            items.append(_eligible_item(card, row_key))
    return items


def _eligible_item(card: CardMetadata, row_key: str) -> EligibleItem:
    return EligibleItem(
        card_id=card.card_id, title=card.title,
        dvids_video_id=card.dvids_video_id, row_key=row_key,
    )


def audio_path_for(item: EligibleItem, audio_dir: Path) -> Path:
    """Local mp4 path for ``item``, one file per eligible row.

    A card_id backed by one AUD row reads ``<audio_dir>/<card_id>.mp4``, the
    R2 current-pointer naming convention already used for ingested A/V bytes
    (``ingest_release_videos.ingest_one``'s ``current_key = f"{card_id}.mp4"``),
    so an operator can stage the same file this stage will later archive under.
    Rows sharing a card_id each get their own file, named with the row key, so
    two rows can never resolve to one set of bytes.
    """
    stem = item.card_id if not item.row_key else f"{item.card_id}-{item.row_key}"
    return audio_dir / f"{stem}.mp4"
