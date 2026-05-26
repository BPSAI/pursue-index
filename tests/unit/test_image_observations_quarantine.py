"""Tests for the image-observations quarantine hook in embed_cli.

When an operator has produced verified image observations for a card
(via the new pursue-curate image-observations suite, or via direct
examination), those observations supersede the alex-zhang42/ufo-
pursue-open-atlas (Zhang) VLM pass for that card. The embed pipeline
must exclude Zhang's IMAGE-DESCRIPTIONS block from any chunk generated
for the quarantined card_ids — otherwise stale/incorrect VLM text
remains in the search and retrieve corpus alongside our corrections.

These tests pin the per-card filtering: pass-through when no
quarantine, drop-by-card_id when quarantine fires, idempotent on
repeated application, graceful on missing/malformed index files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.cli.embed_cli import _apply_image_observations_quarantine


def _index_payload(card_ids: list[str]) -> dict:
    return {
        "schema_version": 1,
        "card_count": len(card_ids),
        "card_ids": card_ids,
        "clusters": {},
    }


def test_passthrough_when_lookup_is_none() -> None:
    """No augment_lookup at all means there's nothing to filter."""
    out = _apply_image_observations_quarantine(None, Path("/nonexistent.json"))
    assert out is None


def test_passthrough_when_quarantine_path_is_none() -> None:
    """No quarantine path means callers opted out — return lookup unchanged."""
    lookup = {("card1", 1): ["augment text"]}
    out = _apply_image_observations_quarantine(lookup, None)
    assert out is lookup


def test_passthrough_when_index_file_missing(tmp_path: Path) -> None:
    """Missing index file is the bootstrap case — no quarantine yet."""
    lookup = {("card1", 1): ["augment text"]}
    out = _apply_image_observations_quarantine(lookup, tmp_path / "missing.json")
    assert out == lookup


def test_passthrough_when_index_has_no_card_ids(tmp_path: Path) -> None:
    """Empty index payload should be a no-op, not crash."""
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index_payload([])))
    lookup = {("card1", 1): ["augment text"]}
    out = _apply_image_observations_quarantine(lookup, index_path)
    assert out == lookup


def test_filters_pages_for_quarantined_card_id(tmp_path: Path) -> None:
    """A card_id in the index should have ALL its pages dropped from the lookup."""
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index_payload(["card_quarantined"])))
    lookup = {
        ("card_quarantined", 1): ["q1"],
        ("card_quarantined", 2): ["q2"],
        ("card_quarantined", 3): ["q3"],
        ("card_kept", 1): ["k1"],
    }
    out = _apply_image_observations_quarantine(lookup, index_path)
    # All pages of the quarantined card dropped; kept card untouched
    assert out is not None
    assert ("card_quarantined", 1) not in out
    assert ("card_quarantined", 2) not in out
    assert ("card_quarantined", 3) not in out
    assert out[("card_kept", 1)] == ["k1"]
    assert len(out) == 1


def test_filters_multiple_card_ids(tmp_path: Path) -> None:
    """Multi-card quarantine list filters all listed cards, keeps the rest."""
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index_payload(["card_a", "card_b"])))
    lookup = {
        ("card_a", 1): ["a1"],
        ("card_b", 1): ["b1"],
        ("card_c", 1): ["c1"],
        ("card_d", 1): ["d1"],
    }
    out = _apply_image_observations_quarantine(lookup, index_path)
    assert out is not None
    assert set(out.keys()) == {("card_c", 1), ("card_d", 1)}


def test_idempotent_on_repeated_application(tmp_path: Path) -> None:
    """Calling twice yields the same result as calling once."""
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index_payload(["card_a"])))
    lookup = {("card_a", 1): ["a1"], ("card_b", 1): ["b1"]}
    first = _apply_image_observations_quarantine(lookup, index_path)
    second = _apply_image_observations_quarantine(first, index_path)
    assert first == second


def test_graceful_on_malformed_json(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Malformed index file warns and returns lookup unchanged — does not crash embed."""
    index_path = tmp_path / "broken.json"
    index_path.write_text("{not valid json}")
    lookup = {("card_a", 1): ["a1"]}
    out = _apply_image_observations_quarantine(lookup, index_path)
    assert out == lookup


def test_lookup_unchanged_if_no_overlap_with_quarantine(tmp_path: Path) -> None:
    """If quarantine list and lookup keys don't overlap, lookup is unchanged."""
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(_index_payload(["unrelated_card"])))
    lookup = {("card_a", 1): ["a1"], ("card_b", 1): ["b1"]}
    out = _apply_image_observations_quarantine(lookup, index_path)
    assert out == lookup
