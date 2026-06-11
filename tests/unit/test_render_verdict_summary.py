"""Unit tests for the pure verdict render helper + artifact builder (T6.4).

T6.4 surfaces the T6.3 ``classify_tranche`` verdict in the operator's view of
a detected tranche. Two PURE helpers live next to ``classify_tranche``:

* ``render_verdict_summary`` — verdict + added/removed/new-column counts ->
  markdown, unit-testable with no GitHub/IO.
* ``build_verdict_artifact`` — the diff+verdict JSON payload the snapshot job
  commits (verdict + counts + new column names), keyed by new_sha.

Both must stay pure (the classify_tranche no-I/O import guard covers the
module). These tests pin the rendered text for BOTH a benign and a
needs-review fixture, and the artifact shape.
"""

from __future__ import annotations

from pursue_index.scrape.classify_tranche import (
    build_verdict_artifact,
    render_verdict_summary,
)
from pursue_index.scrape.poll_snapshot import SnapshotDiffResult
from pursue_index.scrape.types import CardMetadata


def _card(card_id: str = "c0") -> CardMetadata:
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


# --- render_verdict_summary -------------------------------------------------


def test_render_benign_summary() -> None:
    """A field-only diff is benign: the summary must say so and show zero
    structural counts."""
    diff = _diff(
        field_changes=[{"card_id": "c0", "diffs": [{"field": "title"}]}]
    )
    md = render_verdict_summary(diff)
    assert "benign" in md
    assert "needs-review" not in md
    assert "added: 0" in md
    assert "removed: 0" in md
    assert "new columns: 0" in md


def test_render_needs_review_summary_shows_counts_and_columns() -> None:
    """A structural change is needs-review: the summary must flag it and show
    the real added/removed counts plus the new column names."""
    diff = _diff(
        added=[_card("a"), _card("b")],
        removed=[_card("c")],
        new_columns=["Classification", "Tranche"],
    )
    md = render_verdict_summary(diff)
    assert "needs-review" in md
    assert "added: 2" in md
    assert "removed: 1" in md
    assert "new columns: 2" in md
    # The actual column names must surface so the operator sees the schema add.
    assert "Classification" in md
    assert "Tranche" in md


def test_render_includes_field_changes_count() -> None:
    """field_changes don't flip the verdict but are still useful context."""
    diff = _diff(
        added=[_card("a")],
        field_changes=[{"card_id": "c0", "diffs": [{"field": "title"}]}],
    )
    md = render_verdict_summary(diff)
    assert "field changes: 1" in md


# --- build_verdict_artifact -------------------------------------------------


def test_artifact_shape_benign() -> None:
    diff = _diff()
    art = build_verdict_artifact(diff, new_sha="abc123")
    assert art == {
        "new_sha": "abc123",
        "verdict": "benign",
        "added": 0,
        "removed": 0,
        "field_changes": 0,
        "new_columns": [],
    }


def test_artifact_shape_needs_review() -> None:
    diff = _diff(
        added=[_card("a"), _card("b")],
        removed=[_card("c")],
        field_changes=[{"card_id": "c0", "diffs": []}],
        new_columns=["Tranche"],
    )
    art = build_verdict_artifact(diff, new_sha="deadbeef")
    assert art["verdict"] == "needs-review"
    assert art["added"] == 2
    assert art["removed"] == 1
    assert art["field_changes"] == 1
    assert art["new_columns"] == ["Tranche"]
    assert art["new_sha"] == "deadbeef"


def test_render_sanitizes_malicious_column_names() -> None:
    """Regression: new column names come from the upstream CSV header
    (attacker-tunable). Backticks/newlines must be stripped so they can't break
    out of the markdown inline-code span and inject content; length is bounded."""
    evil = "evil`)`\n## injected heading\n" + "x" * 200
    summary = render_verdict_summary(_diff(new_columns=[evil]))
    lines = summary.splitlines()
    # The injected `##` can't become a real markdown heading: no line STARTS
    # with it (the column text is confined to the single "new columns:" line,
    # inside a code span, where `##` renders literally and harmlessly).
    assert not any(ln.lstrip().startswith("#") for ln in lines)
    # No backtick from the column survives to break out of the inline-code span.
    assert "`)`" not in summary
    # The column renders on ONE bounded line (newlines stripped, length capped).
    col_render_line = next(ln for ln in lines if "new columns:" in ln)
    assert len(col_render_line) < 160  # bounded, not 200+ chars
    assert "…" in col_render_line  # truncation marker present for the long name
