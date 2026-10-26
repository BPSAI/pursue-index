"""Which cards the poll lane counts pages for (R7C.5).

New PDF cards (the diff's ``added``) and existing cards whose PDF moved -- a
``field_changes`` entry that touches ``asset_url`` -- the credential-free
lane's view of "byte-changed", since it has no registry to compare bytes
against. One target per card_id; non-PDF assets are not fetched.
"""

from __future__ import annotations

from pursue_index.scrape.pdf_pages import PageTarget, page_targets
from pursue_index.scrape.poll_snapshot import SnapshotDiffResult
from pursue_index.scrape.types import CardMetadata

_BASE = "https://www.war.gov/medialink/ufo"


def _card(card_id: str, asset_type: str, url: str | None) -> CardMetadata:
    return CardMetadata(card_id=card_id, title=card_id, asset_type=asset_type,
                        agency="FBI", asset_url=url)


def _diff(added=(), field_changes=()) -> SnapshotDiffResult:
    return SnapshotDiffResult(added=list(added), removed=[],
                              field_changes=list(field_changes), new_columns=[])


def test_added_pdf_cards_are_targets_and_other_assets_are_not() -> None:
    diff = _diff(added=[
        _card("aaaa000000000001", "PDF", f"{_BASE}/a.pdf"),
        _card("bbbb000000000002", "VID", "https://www.dvidshub.net/video/1"),
        _card("cccc000000000003", "PDF", None),
    ])
    assert page_targets(diff) == [PageTarget("aaaa000000000001", f"{_BASE}/a.pdf")]


def test_a_card_id_with_several_rows_is_fetched_once() -> None:
    diff = _diff(added=[
        _card("aaaa000000000001", "VID", "https://www.dvidshub.net/video/1"),
        _card("aaaa000000000001", "PDF", f"{_BASE}/a.pdf"),
        _card("aaaa000000000001", "PDF", f"{_BASE}/a-dup.pdf"),
    ])
    assert page_targets(diff) == [PageTarget("aaaa000000000001", f"{_BASE}/a.pdf")]


def test_a_field_change_that_moves_a_pdf_is_a_target() -> None:
    diff = _diff(field_changes=[
        {"card_id": "dddd000000000004",
         "diffs": [{"field": "asset_url", "old": f"{_BASE}/old.pdf", "new": f"{_BASE}/new.PDF"}]},
        {"card_id": "eeee000000000005",
         "diffs": [{"field": "title", "old": "x", "new": "y"}]},
        {"card_id": "ffff000000000006",
         "diffs": [{"field": "asset_url", "old": "a.jpg", "new": f"{_BASE}/b.jpg"}]},
    ])
    assert page_targets(diff) == [PageTarget("dddd000000000004", f"{_BASE}/new.PDF")]
