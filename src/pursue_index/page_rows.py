"""The one rule for which OCR row stands for a page.

Append-only sidecars (``pages.jsonl``, ``pages_cleaned.jsonl``) accumulate
duplicate rows for a page after re-runs. ``latest_per_page`` keeps one row per
page, the latest by ``(generated_at, file order)``. The cleaned-page builder
and the model-staleness report both use it, so what ships and what is checked
for staleness cannot drift apart.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from typing import Any

__all__ = ["latest_per_page"]


def latest_per_page(rows: Iterable[dict[str, Any]], card_id: str = "") -> list[dict[str, Any]]:
    """One row per page, latest by ``(generated_at, file order)``.

    A row whose ``page`` is missing or non-numeric is corrupt, not page 0
    (issue #38): it is logged to stderr as a structured warning and skipped,
    matching the "skip bad rows, don't crash the build" stance.
    """
    by_page: dict[int, tuple[tuple[str, int], dict[str, Any]]] = {}
    for idx, row in enumerate(rows):
        raw_page = row.get("page")
        if raw_page is None:
            print(f"warning clean.build.skip_missing_page card_id={card_id} row_index={idx}",
                  file=sys.stderr)
            continue
        try:
            page = int(raw_page)
        except (ValueError, TypeError):
            print(f"warning clean.build.skip_corrupt_row card_id={card_id} row_index={idx} "
                  f"bad_page={raw_page!r}", file=sys.stderr)
            continue
        key = (row.get("generated_at", ""), idx)
        prior = by_page.get(page)
        if prior is None or key >= prior[0]:
            by_page[page] = (key, row)
    return [row for _, row in by_page.values()]
