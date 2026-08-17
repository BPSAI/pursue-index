"""Tests for ``pursue_index.av_fetch.select`` — release/asset-type row filter.

Mirrors ``scripts/_video_ingest_core.select_av_cards``'s contract (VID/AUD
cards carry ``asset_url=None`` so selection is by ``release_date`` +
``asset_type``, not URL presence) without cross-importing a ``scripts/``
module into the installable package.
"""

from __future__ import annotations

from dataclasses import dataclass

from pursue_index.av_fetch.select import DVIDS_ASSET_TYPES, select_av_rows


@dataclass
class FakeCard:
    card_id: str
    asset_type: str
    release_date: str | None
    dvids_video_id: str | None


_CARDS = [
    FakeCard("a", "VID", "6/12/26", "1001"),
    FakeCard("b", "AUD", "6/12/26", "1002"),
    FakeCard("c", "PDF", "6/12/26", None),
    FakeCard("d", "VID", "5/22/26", "1003"),
    FakeCard("e", "IMG", "6/12/26", None),
]


def test_select_av_rows_filters_by_release_date_and_default_asset_types() -> None:
    rows = select_av_rows(_CARDS, "6/12/26")
    assert [c.card_id for c in rows] == ["a", "b"]


def test_select_av_rows_excludes_other_release_dates() -> None:
    rows = select_av_rows(_CARDS, "5/22/26")
    assert [c.card_id for c in rows] == ["d"]


def test_select_av_rows_excludes_pdf_and_img() -> None:
    rows = select_av_rows(_CARDS, "6/12/26")
    assert all(c.asset_type in DVIDS_ASSET_TYPES for c in rows)


def test_select_av_rows_honors_explicit_asset_types() -> None:
    rows = select_av_rows(_CARDS, "6/12/26", asset_types=("VID",))
    assert [c.card_id for c in rows] == ["a"]


def test_select_av_rows_empty_for_no_match() -> None:
    assert select_av_rows(_CARDS, "1/1/00") == []
