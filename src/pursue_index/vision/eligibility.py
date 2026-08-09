"""Eligibility selection for the vision stage.

Eligible items are IMG-card assets and genuinely image-only PDF pages. The
image-only predicate is exactly the one the embed path already uses — a page
row whose base OCR ``text`` is empty/whitespace (see
``embed.store._read_card_pages``). Selection is *row-aware* within a card_id
group: for a PDF card only the empty-OCR page rows become eligible items, not
the whole card.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import CardMetadata, Manifest


@dataclass(frozen=True)
class EligibleItem:
    """One image the vision stage should examine.

    ``page`` is 1 for an IMG-card asset (single image) or the PDF page number
    for an image-only page. ``image_path`` is the IMG asset for ``img_card`` or
    the *source PDF* for ``image_only_page`` (rendered on demand). ``kind`` is
    ``"img_card"`` or ``"image_only_page"``.
    """

    card_id: str
    page: int
    kind: str
    image_path: Path | None
    title: str


def image_only_pages(pages_path: Path) -> list[int]:
    """Page numbers whose base OCR is empty/whitespace — the image-only rows.

    Mirrors the predicate in ``embed.store._read_card_pages``: a row is
    image-only when ``row["text"].strip()`` is falsy. Returns ``[]`` when the
    OCR output is absent (the card hasn't been OCR'd yet).
    """
    if not pages_path.exists():
        return []
    out: list[int] = []
    with pages_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("text", "") or ""
            if not text.strip():
                out.append(int(row["page"]))
    return out


def _img_card_item(card: CardMetadata) -> EligibleItem | None:
    """One eligible item for an IMG card, or ``None`` if it has no asset bytes."""
    path = asset_path_for(card)
    if path is None:
        return None
    return EligibleItem(
        card_id=card.card_id, page=1, kind="img_card",
        image_path=path, title=card.title,
    )


def _pdf_card_items(card: CardMetadata, ocr_dir: Path) -> list[EligibleItem]:
    """Eligible image-only-page items for a PDF card (row-aware within the card)."""
    pdf_path = asset_path_for(card)
    pages_path = ocr_dir / card.card_id / "pages.jsonl"
    return [
        EligibleItem(
            card_id=card.card_id, page=page, kind="image_only_page",
            image_path=pdf_path, title=card.title,
        )
        for page in image_only_pages(pages_path)
    ]


def select_eligible(
    manifest: Manifest,
    worklist_ids: set[str] | None,
    ocr_dir: Path,
) -> list[EligibleItem]:
    """Eligible items across the manifest, optionally scoped to ``worklist_ids``.

    ``worklist_ids`` of ``None`` is the full-corpus escape hatch (mirrors the
    other heavy stages). Preserves manifest order; within a PDF card the
    image-only page rows are kept in ascending page order.
    """
    items: list[EligibleItem] = []
    for card in manifest.cards:
        if worklist_ids is not None and card.card_id not in worklist_ids:
            continue
        if card.asset_type == "IMG":
            item = _img_card_item(card)
            if item is not None:
                items.append(item)
        elif card.asset_type == "PDF":
            items.extend(_pdf_card_items(card, ocr_dir))
    return items
