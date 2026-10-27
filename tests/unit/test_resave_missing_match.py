"""A quarantine row whose ``matched_against`` id has no ``matches`` entry stays
quarantined instead of aborting the whole tranche diff."""

from __future__ import annotations

from pursue_index.tranche_resave import RESAVE_BUCKET, demote_resaves


def test_matched_id_without_a_matches_entry_stays_quarantined() -> None:
    row = {"new_card_id": "n", "new_byte_sha256": "ca" * 32,
           "matched_against": ["gone", "kept"],
           "matches": [{"card_id": "kept", "reasons": ["title"]}]}
    buckets = {"quarantined": [row]}
    moved = demote_resaves(buckets, lambda old_id, new_sha: "d5" * 32, set(), move=True)
    assert moved == {"kept"}
    assert buckets[RESAVE_BUCKET][0]["old_card_id"] == "kept"


def test_row_with_no_matches_at_all_stays_quarantined() -> None:
    row = {"new_card_id": "n", "new_byte_sha256": "ca" * 32, "matched_against": ["gone"]}
    buckets = {"quarantined": [row]}
    assert demote_resaves(buckets, lambda old_id, new_sha: "d5" * 32, set(), move=True) == set()
    assert buckets["quarantined"] == [row]
    assert RESAVE_BUCKET not in buckets
