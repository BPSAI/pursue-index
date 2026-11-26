"""The NTRS row-key join: a keyed claim reaches one row, an unkeyed one every row.

Fixtures only; nothing here touches the network or the stored artifacts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pursue_index.claim_precedence import positive_claims
from pursue_index.ntrs_source import unresolved_nasa_rows
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


def _card(card_id: str, title: str) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "NASA", "release_date": "5/8/2026"}


def _ntrs_claim(card_id: str, row_key: str = "") -> ResolvedClaim:
    return ResolvedClaim(
        card_id=card_id,
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def _ntrs_sources(card: dict[str, Any], claim: ResolvedClaim, row_key: str) -> list[str]:
    found = positive_claims(card, external=[claim], row_key=row_key)
    return [c.source for c in found if c.source == ResolutionSource.NTRS_METADATA.value]


def test_a_keyed_claim_resolves_only_its_own_row() -> None:
    card = _card("aaaa", "first")
    claim = _ntrs_claim("aaaa", "aaaa#0")
    assert len(_ntrs_sources(card, claim, "aaaa#0")) == 1
    assert _ntrs_sources(card, claim, "aaaa#1") == []


def test_an_unkeyed_claim_still_matches_on_card_id() -> None:
    card = _card("aaaa", "first")
    claim = _ntrs_claim("aaaa")
    assert len(_ntrs_sources(card, claim, "aaaa#0")) == 1
    assert len(_ntrs_sources(card, claim, "aaaa#1")) == 1


def test_a_claim_for_another_card_id_never_matches() -> None:
    claim = _ntrs_claim("bbbb", "bbbb#0")
    assert _ntrs_sources(_card("aaaa", "first"), claim, "aaaa#0") == []


def test_unresolved_rows_are_distinct_entries_by_row_key() -> None:
    manifest = {"cards": [_card("aaaa", "first"), _card("aaaa", "second"), _card("bbbb", "other")]}
    rows = unresolved_nasa_rows(manifest)
    assert [key for key, _ in rows] == ["aaaa#0", "aaaa#1", "bbbb#0"]
    assert [card["title"] for _, card in rows] == ["first", "second", "other"]
