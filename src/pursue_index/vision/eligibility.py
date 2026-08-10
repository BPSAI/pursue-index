"""Eligibility selection for the vision stage.

Eligible items are IMG-card assets and genuinely image-only PDF pages. The
image-only predicate is exactly the one the embed path already uses — a page
row whose base OCR ``text`` is empty/whitespace (see
``embed.store._read_card_pages``). Selection is *row-aware* in both directions:

* Within a card, only the empty-OCR page rows of a PDF become eligible items,
  not the whole card.
* Within a ``card_id``, each backing manifest row is its own unit of work. A
  card_id can be backed by more than one row — the upstream CSV's real shape —
  so every item carries a ``row_key`` that separates the rows sharing an id.
  One eligible row can therefore never stand in for another's coverage.
"""

from __future__ import annotations

import json
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.tranche_rows import row_identity_key

CoverageKey = tuple[str, str, int]


@dataclass(frozen=True)
class EligibleItem:
    """One image the vision stage should examine.

    ``page`` is 1 for an IMG-card asset (single image) or the PDF page number
    for an image-only page. ``image_path`` is the IMG asset for ``img_card`` or
    the *source PDF* for ``image_only_page`` (rendered on demand). ``kind`` is
    ``"img_card"`` or ``"image_only_page"``. ``row_key`` names which of a
    card_id's manifest rows this item came from, and is empty for the ordinary
    case of a card_id backed by exactly one eligible row.
    """

    card_id: str
    page: int
    kind: str
    image_path: Path | None
    title: str
    row_key: str = ""

    @property
    def coverage_key(self) -> CoverageKey:
        """The unit coverage is counted in: ``(card_id, row_key, page)``."""
        return (self.card_id, self.row_key, self.page)


def image_only_pages(pages_path: Path) -> list[int]:
    """Page numbers whose base OCR is empty/whitespace — the image-only rows.

    Mirrors the predicate in ``embed.store._read_card_pages``: a row is
    image-only when ``row["text"].strip()`` is falsy. Returns ``[]`` when the
    OCR output is absent (the card hasn't been OCR'd yet).
    """
    if not pages_path.exists():
        return []
    out: list[int] = []
    with pages_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("text", "") or ""
            if not text.strip():
                out.append(int(row["page"]))
    return out


def _identity_token(card: CardMetadata) -> str:
    """The card's row identity, rendered as a key fragment.

    Reuses ``tranche_rows.row_identity_key`` — the single definition of what
    tells two rows of one card_id apart — so the vision stage and the tranche
    diff agree on row identity.
    """
    values = row_identity_key(card.model_dump())
    return "|".join("" if v is None else str(v) for v in values)


def _row_keys(rows: list[CardMetadata]) -> list[str]:
    """A discriminator per row for the rows sharing one card_id.

    A card_id backed by a single eligible row needs no discriminator and gets
    an empty key, which keeps the sidecar shape of the ordinary card unchanged.
    Rows that share an id are separated by their row identity, and by their
    position within the group when identity alone does not separate them — so
    the number of coverage keys always equals the number of eligible rows.
    """
    if len(rows) == 1:
        return [""]
    tokens = [_identity_token(row) for row in rows]
    totals = Counter(tokens)
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for token in tokens:
        seen[token] += 1
        keys.append(token if totals[token] == 1 else f"{token}#{seen[token]}")
    return keys


def _img_card_item(card: CardMetadata, row_key: str) -> EligibleItem | None:
    """One eligible item for an IMG card, or ``None`` if it has no asset bytes."""
    path = asset_path_for(card)
    if path is None:
        return None
    return EligibleItem(
        card_id=card.card_id, page=1, kind="img_card",
        image_path=path, title=card.title, row_key=row_key,
    )


def _pdf_card_items(
    card: CardMetadata, row_key: str, ocr_dir: Path
) -> list[EligibleItem]:
    """Eligible image-only-page items for a PDF card (row-aware within the card)."""
    pdf_path = asset_path_for(card)
    pages_path = ocr_dir / card.card_id / "pages.jsonl"
    return [
        EligibleItem(
            card_id=card.card_id, page=page, kind="image_only_page",
            image_path=pdf_path, title=card.title, row_key=row_key,
        )
        for page in image_only_pages(pages_path)
    ]


def _items_for_row(
    card: CardMetadata, row_key: str, ocr_dir: Path
) -> list[EligibleItem]:
    """Every eligible item contributed by one manifest row."""
    if card.asset_type == "IMG":
        item = _img_card_item(card, row_key)
        return [] if item is None else [item]
    if card.asset_type == "PDF":
        return _pdf_card_items(card, row_key, ocr_dir)
    return []


def select_eligible(
    manifest: Manifest,
    worklist_ids: set[str] | None,
    ocr_dir: Path,
) -> list[EligibleItem]:
    """Eligible items across the manifest, optionally scoped to ``worklist_ids``.

    ``worklist_ids`` of ``None`` is the full-corpus escape hatch (mirrors the
    other heavy stages). Rows are grouped by card_id in order of first
    appearance so each group's row keys are assigned together; within a PDF row
    the image-only page rows are kept in ascending page order.
    """
    groups: OrderedDict[str, list[CardMetadata]] = OrderedDict()
    for card in manifest.cards:
        if worklist_ids is not None and card.card_id not in worklist_ids:
            continue
        if card.asset_type in ("IMG", "PDF"):
            groups.setdefault(card.card_id, []).append(card)

    items: list[EligibleItem] = []
    for rows in groups.values():
        for card, row_key in zip(rows, _row_keys(rows), strict=True):
            items.extend(_items_for_row(card, row_key, ocr_dir))
    return items
