"""Classification of the cards a tranche adds (split from ``tranche_diff``).

Each added card_id lands in one bucket (rename, new content, quarantined or
restored) from its byte sha and the removed rows it might continue.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pursue_index.asset_rows import rows_of_asset
from pursue_index.tranche import build_byte_sha_index, find_title_continuity
from pursue_index.tranche_resave import resave_counts

__all__ = ["build_byte_sha_index"]  # re-exported for tranche_diff


def _classify_restoration(
    cid: str,
    new_card: dict[str, Any],
    sha: str | None,
    prior_rows: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Restoration sub-classifier: card_id is already in the registry,
    which means we've archived bytes under this card_id before. Decide
    whether the reappearance is byte-identical (safe) or modified
    (suspicious).
    """
    pinned_sha = prior_rows[-1].get("byte_sha256")
    base = {
        "new_card_id": cid,
        "new_title": new_card.get("title"),
        "new_asset_filename": new_card.get("asset_filename"),
        "new_asset_url": new_card.get("asset_url"),
        "pinned_byte_sha256": pinned_sha,
        "pinned_fetched_at": prior_rows[-1].get("fetched_at"),
    }
    if sha is None:
        return ("RESTORED_UNKNOWN", {**base, "new_byte_sha256": None})
    base["new_byte_sha256"] = sha
    if sha == pinned_sha:
        return ("RESTORED_UNCHANGED", base)
    return ("RESTORED_MODIFIED", base)


def _classify_added_card(
    cid: str,
    new_card: dict[str, Any],
    sha: str | None,
    sha_to_old_card_ids: dict[str, list[str]],
    removed_old_cards: list[dict[str, Any]],
    registry: dict[str, list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    """Decide the class for one added card. Returns (label, row_dict)
    where label is one of:
      RESTORED_UNCHANGED, RESTORED_MODIFIED, RESTORED_UNKNOWN, A, B, C.

    Restoration takes precedence over A/B/C — if we've previously
    archived this exact card_id under any circumstance (including a
    /removed pin), the reappearance is a restoration event regardless
    of byte-sha collisions with other card_ids.
    """
    # Only this asset's rows: a card's newest row may belong to another asset.
    prior_rows = rows_of_asset(
        registry.get(cid), new_card.get("asset_url"), new_card.get("asset_filename"))
    if prior_rows:
        return _classify_restoration(cid, new_card, sha, prior_rows)
    if sha and sha in sha_to_old_card_ids:
        old_id = sha_to_old_card_ids[sha][0]
        return ("A", {
            "old_card_id": old_id,
            "new_card_id": cid,
            "byte_sha256": sha,
            "new_title": new_card.get("title"),
            "new_asset_filename": new_card.get("asset_filename"),
            "new_asset_url": new_card.get("asset_url"),
        })
    matches = find_title_continuity(new_card, removed_old_cards)
    if matches:
        # Preserve per-match data so the report can show signal strength
        # per candidate rather than unioning reasons across all candidates
        # (which loses the operator's ability to distinguish "strong
        # match on numeric_id + agency" from "weak match on shared
        # location alone"). Rank by reason count descending — more
        # heuristics firing = stronger candidate.
        ranked = sorted(matches, key=lambda m: -len(m["reasons"]))
        return ("C", {
            "new_card_id": cid,
            "new_title": new_card.get("title"),
            "new_asset_filename": new_card.get("asset_filename"),
            "new_asset_url": new_card.get("asset_url"),
            "new_byte_sha256": sha,
            "matched_against": [m["card_id"] for m in ranked],
            "matches": [
                {
                    "card_id": m["card_id"],
                    "title": (m["card"].get("title") or "")[:80],
                    "reasons": m["reasons"],
                    "strength": len(m["reasons"]),
                }
                for m in ranked
            ],
        })
    return ("B", {
        "new_card_id": cid,
        "title": new_card.get("title"),
        "asset_filename": new_card.get("asset_filename"),
        "asset_url": new_card.get("asset_url"),
        "byte_sha256": sha,
    })


def _classify_added_cards(
    added_ids: set[str],
    new_by_id: dict[str, dict[str, Any]],
    sha_to_old_card_ids: dict[str, list[str]],
    removed_old_cards: list[dict[str, Any]],
    registry: dict[str, list[dict[str, Any]]],
    fetch_byte_sha: Callable[[str], str | None],
) -> dict[str, Any]:
    """Run classification across every added card_id. Returns a dict
    holding all classification buckets plus matched_old_ids (used by
    the caller to suppress entries from the removed list).
    """
    buckets: dict[str, list] = {
        "renames_confirmed": [],
        "new_content": [],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "restored_unknown": [],
    }
    matched_old_ids: set[str] = set()
    label_to_bucket = {
        "A": "renames_confirmed",
        "B": "new_content",
        "C": "quarantined",
        "RESTORED_UNCHANGED": "restored_unchanged",
        "RESTORED_MODIFIED": "restored_modified",
        "RESTORED_UNKNOWN": "restored_unknown",
    }
    for cid in sorted(added_ids):
        new_card = new_by_id[cid]
        url = new_card.get("asset_url")
        sha = fetch_byte_sha(url) if url else None
        klass, row = _classify_added_card(
            cid, new_card, sha, sha_to_old_card_ids, removed_old_cards, registry
        )
        buckets[label_to_bucket[klass]].append(row)
        if klass == "A":
            matched_old_ids.add(row["old_card_id"])
    buckets["matched_old_ids"] = matched_old_ids
    return buckets


def _summary(buckets: dict[str, Any], removed: list, field_only_changes: list,
             row_change_list: list) -> dict[str, int]:
    return {
        "renames_confirmed": len(buckets["renames_confirmed"]),
        "new_content": len(buckets["new_content"]),
        "quarantined": len(buckets["quarantined"]),
        **resave_counts(buckets),
        "restored_unchanged": len(buckets["restored_unchanged"]),
        "restored_modified": len(buckets["restored_modified"]),
        "restored_unknown": len(buckets["restored_unknown"]),
        "removed": len(removed),
        "field_only_changes": len(field_only_changes),
        "row_changes": len(row_change_list),
    }
