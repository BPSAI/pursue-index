"""The per-page cost estimate quoted by ``pursue ingest run`` and ``approve``.

Prices the tranche's PDF/IMG work-list (``summarize_ingest_work``'s
``needs_download``) with :mod:`pursue_index.release.rates`. A tranche-diff
row that carries a positive integer ``page_count`` is priced per page; any
other card falls back to the per-card guess, and the figure says so. The
judge rate comes from the committed clean-qc bundle under the data root.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pursue_index.paths import repo_root
from pursue_index.release.estimate_text import estimate_lines, estimate_record
from pursue_index.release.rates import read_judge_rate


def default_bundle_path() -> Path:
    return repo_root() / "web" / "public" / "data" / "clean-qc-bundle.json"


_ROW_LISTS = ("new_content", "quarantined", "renames_confirmed")


def _pages_and_fallbacks(
    diff: dict[str, Any], summary: dict[str, Any], card_ids: Sequence[str] | None = None
) -> tuple[int, list[str]]:
    counts: dict[str, int] = {}
    for key in _ROW_LISTS:
        for row in diff.get(key, []) or []:
            n = row.get("page_count")
            if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                counts[row.get("new_card_id", "")] = n
    work = list(card_ids) if card_ids is not None else summary.get("needs_download") or []
    return sum(counts.get(cid, 0) for cid in work), [cid for cid in work if cid not in counts]


def _inputs(
    diff: dict[str, Any], summary: dict[str, Any], bundle: Path | None,
    card_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    pages, fallback = _pages_and_fallbacks(diff, summary, card_ids)
    judge = read_judge_rate(bundle or default_bundle_path())
    return {"pages": pages, "fallback_card_ids": fallback, "judge": judge}


def ingest_estimate_text(
    diff: dict[str, Any], summary: dict[str, Any], bundle: Path | None = None,
    card_ids: Sequence[str] | None = None,
) -> str:
    """The estimate as text; empty when the tranche has nothing to OCR.

    ``card_ids`` is the exact scoped work-list when the caller has computed it
    (``--from-diff``); without it the Class-B ``needs_download`` list is priced.
    """
    if not (card_ids if card_ids is not None else summary.get("needs_download")):
        return ""
    return "\n".join(estimate_lines(**_inputs(diff, summary, bundle, card_ids)))


def ingest_estimate_record(
    diff: dict[str, Any], summary: dict[str, Any], bundle: Path | None = None
) -> dict[str, Any]:
    """The estimate as the approval record's ``cost_estimate`` row."""
    return estimate_record(**_inputs(diff, summary, bundle))
