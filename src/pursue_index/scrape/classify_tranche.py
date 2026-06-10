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

from typing import Literal

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
