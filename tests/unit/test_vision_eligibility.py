"""Eligibility selection for the vision stage (pipeline stage 6).

Eligible = IMG-card assets + genuinely image-only PDF pages (zero base OCR,
the same predicate the embed path uses in ``embed.store._read_card_pages``).
Selection is *row-aware* within a card_id group: for a PDF card only the
empty-OCR page rows are eligible, not the whole card.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.vision.eligibility import (
    EligibleItem,
    image_only_pages,
    select_eligible,
)


def _manifest(cards: list[CardMetadata]) -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )


def _img_card(card_id: str, **over: object) -> CardMetadata:
    fields: dict = dict(
        card_id=card_id,
        title=f"IMG {card_id}",
        asset_type="IMG",
        agency="FBI",
        asset_url="https://media.defense.gov/x.jpg",
        asset_filename=f"{card_id}.jpg",
    )
    fields.update(over)
    return CardMetadata(**fields)


def _pdf_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title=f"PDF {card_id}",
        asset_type="PDF",
        agency="FBI",
        asset_url="https://media.defense.gov/x.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def _write_pages(ocr_dir: Path, card_id: str, rows: list[dict]) -> None:
    d = ocr_dir / card_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"status": "ok"}))
    with (d / "pages.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_image_only_pages_selects_empty_ocr_rows(tmp_path: Path) -> None:
    _write_pages(
        tmp_path,
        "cardP",
        [
            {"page": 1, "text": "some real ocr text"},
            {"page": 2, "text": "   "},
            {"page": 3, "text": ""},
            {"page": 4, "text": "more text"},
        ],
    )
    assert image_only_pages(tmp_path / "cardP" / "pages.jsonl") == [2, 3]


def test_image_only_pages_missing_file_is_empty(tmp_path: Path) -> None:
    assert image_only_pages(tmp_path / "nope" / "pages.jsonl") == []


def test_select_img_cards(tmp_path: Path) -> None:
    m = _manifest([_img_card("imgA"), _img_card("imgB")])
    items = select_eligible(m, None, tmp_path)
    assert {(i.card_id, i.page, i.kind) for i in items} == {
        ("imgA", 1, "img_card"),
        ("imgB", 1, "img_card"),
    }
    # img_card items point at the downloaded asset path
    a = next(i for i in items if i.card_id == "imgA")
    assert a.image_path is not None and a.image_path.name == "imgA.jpg"


def test_select_is_row_aware_within_pdf_card(tmp_path: Path) -> None:
    m = _manifest([_pdf_card("cardP")])
    _write_pages(
        tmp_path,
        "cardP",
        [
            {"page": 1, "text": "real text"},
            {"page": 2, "text": ""},
            {"page": 3, "text": ""},
        ],
    )
    items = select_eligible(m, None, tmp_path)
    # Only the two image-only rows, not the whole card.
    assert {(i.card_id, i.page) for i in items} == {("cardP", 2), ("cardP", 3)}
    assert all(i.kind == "image_only_page" for i in items)


def test_worklist_scopes_selection(tmp_path: Path) -> None:
    m = _manifest([_img_card("imgA"), _img_card("imgB")])
    items = select_eligible(m, {"imgA"}, tmp_path)
    assert {i.card_id for i in items} == {"imgA"}


def test_img_card_without_asset_is_skipped(tmp_path: Path) -> None:
    bad = CardMetadata(
        card_id="noasset", title="x", asset_type="IMG", agency="FBI"
    )  # no asset_url/filename -> asset_path_for None
    m = _manifest([bad])
    assert select_eligible(m, None, tmp_path) == []


def test_pdf_without_ocr_yields_nothing(tmp_path: Path) -> None:
    m = _manifest([_pdf_card("cardP")])  # no pages.jsonl written
    assert select_eligible(m, None, tmp_path) == []


def test_single_row_card_carries_an_empty_row_key(tmp_path: Path) -> None:
    """A card_id backed by one manifest row needs no row discriminator."""
    m = _manifest([_img_card("imgA")])
    (item,) = select_eligible(m, None, tmp_path)
    assert item.row_key == ""
    assert item.coverage_key == ("imgA", "", 1)


def test_duplicate_card_id_rows_each_stay_eligible(tmp_path: Path) -> None:
    """Both image rows under one card_id are selected and keyed apart.

    A card_id can be backed by more than one manifest row — the upstream CSV's
    real shape. Each row is its own unit of work, so each carries a distinct
    coverage key and neither can satisfy the other's coverage.
    """
    m = _manifest([
        _img_card("dupe", dvids_video_id="1006080", video_title=""),
        _img_card("dupe", dvids_video_id="1006080", video_title="Second release"),
    ])
    items = select_eligible(m, None, tmp_path)
    assert len(items) == 2
    assert len({i.coverage_key for i in items}) == 2
    assert {i.card_id for i in items} == {"dupe"}


def test_duplicate_rows_with_identical_identity_still_key_apart(
    tmp_path: Path,
) -> None:
    """Rows whose identity fields match are still distinguished from each other.

    Row identity normally separates rows inside a card_id group. When it does
    not, position within the group completes the key, so the number of eligible
    units always equals the number of eligible rows.
    """
    m = _manifest([_img_card("dupe"), _img_card("dupe"), _img_card("dupe")])
    items = select_eligible(m, None, tmp_path)
    assert len(items) == 3
    assert len({i.coverage_key for i in items}) == 3


def test_eligible_item_is_hashable() -> None:
    item = EligibleItem(
        card_id="a", page=1, kind="img_card", image_path=Path("x"), title="t"
    )
    assert item in {item}
