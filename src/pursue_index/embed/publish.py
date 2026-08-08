"""Row selection shared by the embed index rewrite and the published payloads.

The embed store is append-only: ``pipeline._select_new_rows`` keys "already
embedded?" on ``(card_id, page, text_sha)``, so re-OCR'ing a page mints a new
row and the prior row for that page stays behind. Every consumer wants one row
per ``(card_id, page)``, and the row it wants is the newest one — which, in an
append-only store, is the last one in store (offset-ascending) order.

``dedupe_latest_wins`` is that rule. ``load_embed_eligible_keys`` /
``select_publish_rows`` add the publish-side gate: a page is publishable only
if ``pages.json`` carries non-empty text for it, since that file is what
``/api/retrieve`` reads titles and snippets from. A row without a text-bearing
``pages.json`` entry can only ever produce a blank citation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, TypeVar

RowT = TypeVar("RowT")

PageKey = tuple[str, int]


def dedupe_latest_wins(
    rows: Sequence[RowT], key: Callable[[RowT], PageKey]
) -> list[RowT]:
    """Keep the last row per ``key``, in the order the kept rows appear.

    Input order is store order (append order == ascending offset), so "last"
    is "most recently embedded". The output preserves the relative order of
    the rows that survive, which keeps offset-sorted input offset-sorted.
    """
    seen: set[PageKey] = set()
    kept: list[RowT] = []
    for row in reversed(rows):
        k = key(row)
        if k in seen:
            continue
        seen.add(k)
        kept.append(row)
    kept.reverse()
    return kept


def index_row_key(row: dict[str, Any]) -> PageKey:
    """``(card_id, page)`` for a JSON index row."""
    return (str(row["card_id"]), int(row["page"]))


def load_embed_eligible_keys(pages_json_path: Path) -> set[PageKey]:
    """``(card_id, page)`` for every ``pages.json`` entry with non-empty text.

    Pages with no readable text are embed-ineligible: they carry no retrievable
    content and a citation built from one would have an empty snippet.
    """
    entries = json.loads(pages_json_path.read_text())
    return {
        (str(e["card_id"]), int(e["page"]))
        for e in entries
        if (e.get("text") or "").strip()
    }


def select_publish_rows(
    rows: Iterable[dict[str, Any]], eligible: set[PageKey]
) -> list[dict[str, Any]]:
    """Offset-sorted, eligibility-filtered, one row per ``(card_id, page)``.

    Shared by ``scripts/build_embed_data.py`` and
    ``scripts/build_atlas_layout.py`` so the published embedding payload and
    the atlas layout always reference the same row set.
    """
    ordered = sorted(rows, key=lambda r: int(r["offset"]))
    publishable = [r for r in ordered if index_row_key(r) in eligible]
    return dedupe_latest_wins(publishable, index_row_key)
