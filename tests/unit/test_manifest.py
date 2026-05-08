"""Round-trip + diff tests for the manifest module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pursue_index.scrape.manifest import load_manifest, save_manifest
from pursue_index.scrape.types import CardMetadata, Manifest


def _card(card_id: str, agency: str = "FBI") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        pdf_url=f"https://www.war.gov/medialink/ufo/release_1/{card_id}.pdf",
        pdf_filename=f"{card_id}.pdf",
        agency=agency,
    )


def test_manifest_roundtrip(tmp_path: Path) -> None:
    m = Manifest(
        source_url="https://www.war.gov/UFO/",
        scraped_at=datetime.now(UTC),
        cards=[_card("a"), _card("b")],
    )
    out = tmp_path / "manifest.json"
    save_manifest(m, out)

    loaded = load_manifest(out)
    assert loaded.card_count == 2
    assert {c.card_id for c in loaded.cards} == {"a", "b"}


def test_manifest_diff_added_and_removed() -> None:
    now = datetime.now(UTC)
    old = Manifest(
        source_url="https://www.war.gov/UFO/",
        scraped_at=now,
        cards=[_card("a"), _card("b")],
    )
    new = Manifest(
        source_url="https://www.war.gov/UFO/",
        scraped_at=now,
        cards=[_card("b"), _card("c")],
    )
    diff = new.diff(old)
    assert {c.card_id for c in diff.added} == {"c"}
    assert {c.card_id for c in diff.removed} == {"a"}
    assert diff.has_changes is True
