"""Stored NTRS claims with an empty, missing or malformed card_id are refused and counted."""

from __future__ import annotations

from typing import Any

from pursue_index.claim_precedence import positive_claims
from pursue_index.ntrs_claims_load import load_ntrs_claims

GOOD = "0123456789abcdef"


def _row(card_id: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "tier": "content_previously_published",
        "source": "ntrs_metadata",
        "artifact_url": "https://ntrs.nasa.gov/citations/1",
        "established_date": "2020-01-01",
        "date_basis": "ntrs_distribution_date",
    }
    if card_id is not None:
        row["card_id"] = card_id
    return row


def test_bad_ids_are_refused_counted_and_resolve_no_card() -> None:
    data = {"claims": [_row(GOOD), _row(""), _row("not-a-card-id"), _row(None), _row("  ")]}
    loaded = load_ntrs_claims(data)
    assert [c.card_id for c in loaded.claims] == [GOOD]
    assert loaded.refused_claims == 4
    for card in ({"card_id": ""}, {}, {"card_id": "not-a-card-id"}):
        assert positive_claims(card, (), loaded.claims) == []


def test_all_valid_claims_count_no_refusals() -> None:
    assert load_ntrs_claims({"claims": [_row(GOOD)]}).refused_claims == 0
