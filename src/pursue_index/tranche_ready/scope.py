"""The record's ``scope`` and ``pages`` blocks.

``scope`` is the R7C.1 PDF/IMG worklist (``ingest_scope.scope_pdf_img_cards``)
as data, with one refinement the worklist cannot make at poll time: a
quarantined card whose candidate is recommended for a rename is scoped as
``renamed`` (the hand-off's recommendation), not ``quarantined-new``.

``pages`` totals the page counter's counts over the scoped cards. A scoped
card with no count is a fallback: priced per card, and it makes the page
count ``partial`` (``unavailable`` when nothing was counted).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pursue_index.ingest_scope import REASON_QUARANTINED_NEW, REASON_RENAMED, scope_pdf_img_cards
from pursue_index.tranche_manifest import display_rows_by_card_id

__all__ = ["LARGEST_SHOWN", "pages_block", "scope_cards"]

# How many of the largest documents the record lists (the pinned example's four).
LARGEST_SHOWN = 4
_DOC_ID = re.compile(r"[A-Z]+(?:-[A-Z0-9]+)+")


def _doc_id(title: object) -> str | None:
    head = str(title or "").split(",", 1)[0].strip()
    return head if _DOC_ID.fullmatch(head) else None


def _with_doc_id(card_id: str, titles: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    out = {"card_id": card_id, **fields}
    if doc_id := _doc_id(titles.get(card_id)):
        out["doc_id"] = doc_id
    return out


def scope_cards(
    diff: dict[str, Any], tranche_sha: str, new_manifest: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Every scoped card with its reason (and doc id, when the title has one).

    No aliases are read: at poll time no rename for this tranche has been
    approved yet, so the record scopes the tranche as detected.
    """
    renamed = {c["new_card_id"] for c in candidates
               if c["recommended_disposition"].startswith("approve-rename")}
    titles = {cid: row.get("title")
              for cid, row in display_rows_by_card_id(new_manifest.get("cards", [])).items()}
    out = []
    for card in scope_pdf_img_cards(diff, tranche_sha):
        reason = card.reason
        if reason == REASON_QUARANTINED_NEW and card.card_id in renamed:
            reason = REASON_RENAMED
        out.append(_with_doc_id(card.card_id, titles, reason=reason))
    return out


def pages_block(
    scoped: list[dict[str, Any]], page_counts: Mapping[str, int],
) -> tuple[dict[str, Any], list[str]]:
    """``(pages, fallback_card_ids)`` for the scoped cards."""
    counted = [c for c in scoped if c["card_id"] in page_counts]
    fallback = [c["card_id"] for c in scoped if c["card_id"] not in page_counts]
    source = "fetched" if not fallback else ("partial" if counted else "unavailable")
    largest = sorted(counted, key=lambda c: (-page_counts[c["card_id"]], c["card_id"]))
    pages = {
        "total": sum(page_counts[c["card_id"]] for c in counted),
        "source": source,
        "largest": [
            {**{k: v for k, v in c.items() if k != "reason"}, "pages": page_counts[c["card_id"]]}
            for c in largest[:LARGEST_SHOWN]
        ],
    }
    return pages, fallback
