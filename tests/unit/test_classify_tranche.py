"""Unit tests for the lightweight tranche verdict (Sprint 6, T6.3).

``classify_tranche`` is a pure, metadata-only verdict over a T6.1
``SnapshotDiffResult`` — no LLM, no I/O, no network, no R2/byte-sha
registry. It must NOT be confused with the heavy A/B/C/restoration
classifier in ``scripts/tranche_diff.py`` (which fetches bytes).
"""

from __future__ import annotations

import ast
from pathlib import Path

from pursue_index.scrape.classify_tranche import classify_tranche, render_verdict_summary
from pursue_index.scrape.poll_snapshot import SnapshotDiffResult
from pursue_index.scrape.types import CardMetadata


def _card(card_id: str = "c0") -> CardMetadata:
    """Minimal CardMetadata — the verdict only counts cards, never reads fields."""
    return CardMetadata(card_id=card_id, title="t", asset_type="PDF", agency="a")


def _diff(
    *,
    added: list[CardMetadata] | None = None,
    removed: list[CardMetadata] | None = None,
    field_changes: list | None = None,
    new_columns: list[str] | None = None,
) -> SnapshotDiffResult:
    return SnapshotDiffResult(
        added=added or [],
        removed=removed or [],
        field_changes=field_changes or [],
        new_columns=new_columns or [],
    )


def test_empty_diff_is_benign() -> None:
    assert classify_tranche(_diff()) == "benign"


def test_added_card_is_needs_review() -> None:
    assert classify_tranche(_diff(added=[_card("new1")])) == "needs-review"


def test_removed_card_is_needs_review() -> None:
    assert classify_tranche(_diff(removed=[_card("gone1")])) == "needs-review"


def test_new_column_is_needs_review() -> None:
    assert classify_tranche(_diff(new_columns=["Classification"])) == "needs-review"


def test_field_only_change_is_benign() -> None:
    """field_changes alone (0 added / 0 removed / no new column) stays benign.

    The verdict keys ONLY on added/removed/new-column — a metadata edit to an
    existing card is not promotion-worthy. Pinned per the T6.3 grounding.
    """
    field_changes = [{"card_id": "c0", "diffs": [{"field": "title", "old": "a", "new": "b"}]}]
    assert classify_tranche(_diff(field_changes=field_changes)) == "benign"


def test_added_and_removed_together_is_needs_review() -> None:
    verdict = classify_tranche(_diff(added=[_card("a")], removed=[_card("b")]))
    assert verdict == "needs-review"


def test_module_has_no_io_or_network_imports() -> None:
    """Deterministic + pure: the module must not IMPORT the network, R2, or
    the byte-sha registry (the AC's no-I/O guard, enforced structurally).

    Scans only the actual import statements (via ``ast``) so a docstring that
    merely *mentions* these in the negative can't false-positive.
    """
    rel = Path(classify_tranche.__module__.replace(".", "/")).with_suffix(".py")
    src_root = Path(__file__).resolve().parents[2] / "src"
    tree = ast.parse((src_root / rel).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    blob = " ".join(imported).lower()
    for forbidden in ("fetch_raw_csv", "http", "boto", "r2", "requests", "registry", "csv_fetcher"):
        assert forbidden not in blob, f"classify_tranche must not import {forbidden!r}"


def test_render_verdict_summary_appends_ship_footer_only_with_tranche() -> None:
    """T-ship: the alert surfaces the ship-tranche command when the sha is given,
    and stays backward-compatible (verdict-only) when it is not."""
    d = _diff(added=["a", "b"], field_changes=["c"])
    sha = "13e730c18d6ea586bcb9b58984481b093f3e4802c33b0f9281258ee786f8abd1"
    with_footer = render_verdict_summary(d, tranche=sha)
    without = render_verdict_summary(d)
    assert "/ship-tranche 13e730c18d6ea586" in with_footer
    assert "$" in with_footer  # cost estimate surfaced
    assert "/ship-tranche" not in without
    assert "Tranche verdict:" in without
