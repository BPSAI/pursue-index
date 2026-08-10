"""Row-awareness of transcribe eligibility, and how a run is scoped.

A card_id can be backed by more than one manifest row — the upstream CSV's
real shape — so every eligible AUD row is its own unit of work: its own
coverage key and its own source file. Scoping is by ``release_date``,
matching the A/V fetch stage that stages the same rows' bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe.eligibility import audio_path_for, select_eligible


def _card(
    card_id: str,
    asset_type: str,
    *,
    dvids_video_id: str | None = "1006119",
    release_date: str | None = "2026-08-01",
) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"T {card_id}", asset_type=asset_type, agency="NASA",
        dvids_video_id=dvids_video_id, release_date=release_date,
    )


def _manifest(cards: list[CardMetadata]) -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )


def test_two_aud_rows_under_one_card_id_are_two_coverage_units() -> None:
    m = _manifest(
        [
            _card("dup", "AUD", dvids_video_id="1006119"),
            _card("dup", "AUD", dvids_video_id="1006120"),
        ]
    )
    items = select_eligible(m, None)
    assert len(items) == 2
    assert len({i.coverage_key for i in items}) == 2


def test_two_aud_rows_under_one_card_id_resolve_to_distinct_source_files() -> None:
    m = _manifest(
        [
            _card("dup", "AUD", dvids_video_id="1006119"),
            _card("dup", "AUD", dvids_video_id="1006120"),
        ]
    )
    paths = {audio_path_for(i, Path("/audio")) for i in select_eligible(m, None)}
    assert len(paths) == 2


def test_single_row_card_keeps_the_plain_card_id_naming() -> None:
    m = _manifest([_card("aud1", "AUD")])
    item = select_eligible(m, None)[0]
    assert item.row_key == ""
    assert item.coverage_key == ("aud1", "")
    assert audio_path_for(item, Path("/audio")) == Path("/audio/aud1.mp4")


def test_release_date_scopes_selection_to_that_release() -> None:
    m = _manifest(
        [
            _card("old", "AUD", release_date="2026-05-12"),
            _card("new", "AUD", release_date="2026-08-01"),
        ]
    )
    items = select_eligible(m, "2026-08-01")
    assert [i.card_id for i in items] == ["new"]
