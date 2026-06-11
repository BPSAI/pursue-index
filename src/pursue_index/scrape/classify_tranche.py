"""Lightweight tranche verdict (Sprint 6, T6.3).

A pure, metadata-only classifier over a T6.1 :class:`SnapshotDiffResult`.
It decides whether a detected snapshot change is benign (no human attention
needed) or warrants review, using only the manifest-level diff — card counts
and new CSV columns. There is **no LLM, no I/O, no network, and no R2 /
byte-sha registry access**; the verdict is a deterministic function of the
diff alone.

This is intentionally NOT the heavy classifier in ``scripts/tranche_diff.py``
(the byte-fetching A/B/C/restoration analysis that hits the network and the
registry). T6.3 keys only on:

  * ``diff.added``    — cards present in the new snapshot but not the prior
  * ``diff.removed``  — cards present in the prior snapshot but not the new
  * ``diff.new_columns`` — brand-new, unmodeled CSV headers

Per-card ``field_changes`` (an existing card's metadata edited in place) do
**not** flip the verdict — only structural additions/removals or a schema
addition do.

Note: the backlog phrased this as ``classify_tranche(diff, new_columns)``, but
``SnapshotDiffResult`` already carries ``new_columns``, so the function takes
the whole result and consumes T6.1's output directly.
"""

from __future__ import annotations

from typing import Any, Literal

from pursue_index.scrape.poll_snapshot import SnapshotDiffResult

TrancheVerdict = Literal["benign", "needs-review"]


def classify_tranche(diff: SnapshotDiffResult) -> TrancheVerdict:
    """Return the lightweight verdict for a snapshot diff.

    ``benign`` iff there are zero added cards, zero removed cards, and no new
    unmodeled column. Anything else is ``needs-review``.
    """
    if diff.added or diff.removed or diff.new_columns:
        return "needs-review"
    return "benign"


def build_verdict_artifact(diff: SnapshotDiffResult, *, new_sha: str) -> dict[str, Any]:
    """Build the diff+verdict JSON payload the snapshot job commits (T6.4).

    Pure: just the verdict + structural counts (and the new column names),
    keyed by ``new_sha`` so it can be located against the detected change.
    No I/O — the caller serializes + writes it.
    """
    return {
        "new_sha": new_sha,
        "verdict": classify_tranche(diff),
        "added": len(diff.added),
        "removed": len(diff.removed),
        "field_changes": len(diff.field_changes),
        "new_columns": list(diff.new_columns),
    }


def _safe_inline(text: str, *, limit: int = 80) -> str:
    """Sanitize an upstream-derived string for a markdown inline-code span.

    New column names come from the upstream CSV header (attacker-tunable). Drop
    backticks and newlines (which would break out of the `code` span and inject
    markdown) and bound the length so a pathological header can't blow up the
    issue comment.
    """
    cleaned = text.replace("`", "").replace("\n", " ").replace("\r", " ").strip()
    return cleaned[:limit] + "…" if len(cleaned) > limit else cleaned


def render_verdict_summary(diff: SnapshotDiffResult) -> str:
    """Render the verdict + counts as operator-facing markdown (T6.4).

    Pure formatter (no GitHub / no I/O) so it is unit-testable. The snapshot
    job posts this onto the existing ``tranche-detected`` issue once the diff
    is ready.
    """
    verdict = classify_tranche(diff)
    cols = list(diff.new_columns)
    col_line = f"* new columns: {len(cols)}"
    if cols:
        col_line += " — " + ", ".join(f"`{_safe_inline(c)}`" for c in cols)
    return (
        f"**Tranche verdict: `{verdict}`**\n\n"
        f"* added: {len(diff.added)}\n"
        f"* removed: {len(diff.removed)}\n"
        f"* field changes: {len(diff.field_changes)}\n"
        f"{col_line}\n"
    )
