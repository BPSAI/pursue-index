"""Eligibility selection for the transcribe stage — AUD rows only.

VID is never transcribed (radar/FLIR has nothing to transcribe); a VID row
present anywhere in the manifest must be provably excluded. Row-awareness and
release scoping are covered in ``test_transcribe_eligibility_rows``.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe.eligibility import audio_path_for, select_eligible


def _card(card_id: str, asset_type: str, dvids_video_id: str | None = "1006119") -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"T {card_id}", asset_type=asset_type, agency="NASA",
        dvids_video_id=dvids_video_id,
    )


def _manifest(cards: list[CardMetadata]) -> Manifest:
    from datetime import UTC, datetime

    return Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )


def test_select_eligible_includes_aud_and_excludes_vid() -> None:
    m = _manifest([_card("aud1", "AUD"), _card("vid1", "VID"), _card("pdf1", "PDF")])
    items = select_eligible(m, None)
    assert [i.card_id for i in items] == ["aud1"]


def test_select_eligible_none_release_date_is_full_corpus_escape_hatch() -> None:
    m = _manifest([_card("aud1", "AUD"), _card("aud2", "AUD")])
    items = select_eligible(m, None)
    assert {i.card_id for i in items} == {"aud1", "aud2"}


def test_select_eligible_preserves_manifest_order() -> None:
    m = _manifest([_card("aud2", "AUD"), _card("vid1", "VID"), _card("aud1", "AUD")])
    items = select_eligible(m, None)
    assert [i.card_id for i in items] == ["aud2", "aud1"]


def test_select_eligible_carries_title_for_downstream_use() -> None:
    m = _manifest([_card("aud1", "AUD")])
    items = select_eligible(m, None)
    assert items[0].title == "T aud1"


def test_audio_path_for_is_card_id_named_in_audio_dir() -> None:
    m = _manifest([_card("aud1", "AUD")])
    item = select_eligible(m, None)[0]
    path = audio_path_for(item, Path("/tmp/audio"))
    assert path == Path("/tmp/audio/aud1.mp4")


def test_audio_path_for_prefers_card_id_mp4_when_both_exist(tmp_path: Path) -> None:
    """audio_path_for returns card_id.mp4 when both card_id and DOD versions exist."""
    m = _manifest([_card("aud1", "AUD", dvids_video_id="1234567")])
    item = select_eligible(m, None)[0]

    # Both files exist
    card_path = tmp_path / "aud1.mp4"
    dod_path = tmp_path / "DOD_1234567.mp4"
    card_path.write_bytes(b"card data")
    dod_path.write_bytes(b"dod data")

    path = audio_path_for(item, tmp_path)
    # Should prefer card_id.mp4
    assert path == card_path
    assert path.read_bytes() == b"card data"


def test_audio_path_for_falls_back_to_dod_name(tmp_path: Path) -> None:
    """audio_path_for falls back to DOD_<id>.mp4 when card_id.mp4 doesn't exist."""
    m = _manifest([_card("aud1", "AUD", dvids_video_id="1234567")])
    item = select_eligible(m, None)[0]

    # Only DOD file exists
    dod_path = tmp_path / "DOD_1234567.mp4"
    dod_path.write_bytes(b"dod data")

    path = audio_path_for(item, tmp_path)
    # Should resolve to the DOD file since card_id doesn't exist
    assert path == dod_path
    assert path.read_bytes() == b"dod data"
