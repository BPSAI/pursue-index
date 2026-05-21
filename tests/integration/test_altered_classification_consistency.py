"""Cross-consistency invariants between
``data/altered-classification.json`` (Sprint 4k-A + 4k-B) and
``web/src/data/altered-diffs.json`` (Sprint 4j).

These tests make sure the data the /altered/ pages read is internally
consistent — every card listed in byte-history is accounted for, the
diff-vs-classification dispositions match, and the bucket counts in
the meta block agree with the per-card records.

Failure here typically means somebody changed one pipeline output
without re-running the upstream step. The fix is usually to re-run
``scripts/classify_altered_changes.py``,
``scripts/classify_no_text_layer_visually.py``, and
``scripts/build_altered_diffs.py`` in that order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BYTE_HISTORY = REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
CLASSIFICATION = REPO_ROOT / "data" / "altered-classification.json"
ALTERED_DIFFS = REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"


@pytest.fixture(scope="module")
def byte_history() -> dict:
    return json.loads(BYTE_HISTORY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def classification() -> dict:
    return json.loads(CLASSIFICATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def altered_diffs() -> dict:
    return json.loads(ALTERED_DIFFS.read_text(encoding="utf-8"))


def test_classification_covers_every_altered_card(
    byte_history: dict, classification: dict
) -> None:
    """Every card in byte-history.json should have a classification
    entry. New altered events between runs must trigger a re-classify."""
    cards = classification["cards"]
    bh_keys = set(byte_history.keys())
    class_keys = set(cards.keys())
    missing = bh_keys - class_keys
    assert not missing, (
        f"{len(missing)} card(s) in byte-history have no classification entry; "
        f"re-run scripts/classify_altered_changes.py. Missing: {sorted(missing)[:5]}..."
    )


def test_classification_bucket_counts_match_per_card_records(
    classification: dict,
) -> None:
    """_meta.counts should be the count of each `class` value across the
    cards map. Drift here means a manual edit slipped past a re-run."""
    counts = classification["_meta"]["counts"]
    actual_counts: dict[str, int] = {}
    for entry in classification["cards"].values():
        cls = entry["class"]
        actual_counts[cls] = actual_counts.get(cls, 0) + 1
    for cls, n in actual_counts.items():
        assert counts.get(cls) == n, (
            f"_meta.counts.{cls} = {counts.get(cls)} but per-card records "
            f"show {n}"
        )


def test_presentation_only_cards_have_no_diff_entry(
    classification: dict, altered_diffs: dict
) -> None:
    """The diff builder is supposed to SKIP presentation_only cards
    (the OCR diff is non-determinism noise when content is identical).
    Any presentation_only card showing up in diffs is a pipeline drift."""
    diffs = altered_diffs.get("diffs", {})
    leaked = [
        cid for cid, info in classification["cards"].items()
        if info["class"] == "presentation_only" and cid in diffs
    ]
    assert not leaked, (
        f"{len(leaked)} presentation_only card(s) have a diff entry — "
        f"the skip rule in build_altered_diffs.py regressed: {leaked[:3]}"
    )


def test_visually_identical_cards_have_no_diff_entry(
    classification: dict, altered_diffs: dict
) -> None:
    """Same rule, applied to no_text_layer cards whose perceptual-hash
    comparison classified them as visually_identical (Sprint 4k-B)."""
    diffs = altered_diffs.get("diffs", {})
    leaked = [
        cid for cid, info in classification["cards"].items()
        if info.get("visual_class") == "visually_identical" and cid in diffs
    ]
    assert not leaked, (
        f"{len(leaked)} visually_identical card(s) have a diff entry — "
        f"the visual-class skip rule in build_altered_diffs.py regressed: "
        f"{leaked[:3]}"
    )


def test_asset_type_change_cards_have_no_diff_entry(
    classification: dict, altered_diffs: dict
) -> None:
    """asset_type_change cards (video → PDF swap) have no pre-edit text
    to diff against; the per-card page falls through to a "no text-diff"
    message. The diff entry must be absent."""
    diffs = altered_diffs.get("diffs", {})
    leaked = [
        cid for cid, info in classification["cards"].items()
        if info["class"] == "asset_type_change" and cid in diffs
    ]
    assert not leaked, (
        f"{len(leaked)} asset_type_change card(s) have a diff entry: "
        f"{leaked[:3]}"
    )


def test_content_changed_cards_have_diff_entry(
    classification: dict, altered_diffs: dict
) -> None:
    """Every content_changed card whose visual hash CONFIRMS the change
    (visual_class != visually_identical) should have an entry in
    altered-diffs.json.

    content_changed cards that ALSO show visual_class=visually_identical
    are downgraded to presentation_only (text-layer differences are
    typically pure whitespace/tokenization in the embedded text that
    don't reflect visible content change). Those land in
    skipped_presentation_only and are correctly absent from `diffs`.

    Note: this test does NOT assert the diff is non-empty — it's
    occasionally possible for a content_changed + visually_changed
    card to OCR identically on both sides (visual differences in
    margins, formatting tweaks, image regions that Sonnet OCR is
    robust against). Those cards still need an entry so the per-card
    page can render the OCR-mismatch banner instead of silent skip.
    """
    diffs = altered_diffs.get("diffs", {})
    missing = []
    for cid, info in classification["cards"].items():
        if info["class"] != "content_changed":
            continue
        if info.get("visual_class") == "visually_identical":
            continue
        if cid not in diffs:
            missing.append(cid)
    assert not missing, (
        f"content_changed card(s) missing diff entry: {missing[:3]}. "
        "Re-run scripts/build_altered_diffs.py."
    )


def test_meta_block_lists_match_diff_keys(altered_diffs: dict) -> None:
    """``_meta.engine_matched_cards`` should equal the keys in
    ``diffs`` — they're emitted together by build_altered_diffs.py."""
    meta = altered_diffs.get("_meta", {})
    matched = set(meta.get("engine_matched_cards", []))
    diff_keys = set(altered_diffs.get("diffs", {}).keys())
    assert matched == diff_keys, (
        f"_meta.engine_matched_cards has {len(matched)} entries but "
        f"`diffs` has {len(diff_keys)} keys; symmetric difference: "
        f"{sorted(matched ^ diff_keys)[:5]}"
    )


def test_byte_history_pdf_cards_have_visual_class_or_text_class(
    byte_history: dict, classification: dict
) -> None:
    """Sprint 4k-A handles cards with text layers; Sprint 4k-B handles
    no_text_layer cards. Together they should classify every PDF card.

    Cards stuck at `class: no_text_layer` AND missing `visual_class` are
    the QC backlog — the visual-classifier hasn't been run on them yet.
    This test enforces the invariant; when it fires, run
    `scripts/classify_no_text_layer_visually.py`.
    """
    unclassified = []
    for cid, entries in byte_history.items():
        oldest = entries[-1] if entries else {}
        if not oldest.get("archive_key", "").lower().endswith(".pdf"):
            continue  # mp4 → asset_type_change handled separately
        entry = classification["cards"].get(cid, {})
        if entry.get("class") == "no_text_layer" and not entry.get("visual_class"):
            unclassified.append(cid)
    assert not unclassified, (
        f"{len(unclassified)} PDF-historic card(s) lack visual classification; "
        f"run scripts/classify_no_text_layer_visually.py. Affected: "
        f"{unclassified[:5]}"
    )
