"""Re-paginate an existing transcript sidecar in place.

Split out of ``pages``: a sidecar keeps its utterances, so a change of page
budget is re-applied by re-cutting the stored turns rather than
re-transcribing. Reads and writes the same ``pages.jsonl`` / ``meta.json``
that ``pages.write_transcript_sidecar`` produces.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pursue_index.transcribe.pages import (
    _DEFAULT_CHAR_BUDGET,
    _DEFAULT_DURATION_BUDGET_S,
    _read_meta,
    build_pages_rows,
)
from pursue_index.transcribe.utterances_store import read_utterances


def _row_slices(
    rows_meta: list[dict[str, Any]], utterances: list[dict[str, Any]]
) -> list[list[dict[str, Any]]] | None:
    """The stored utterances split per transcribed row, or ``None`` if unknown.

    Utterances are stored flat in row order; each ``rows`` entry records how
    many it contributed. A single-row card needs no counts.
    """
    if len(rows_meta) <= 1:
        return [utterances]
    counts = [r.get("utterances") for r in rows_meta]
    if any(not isinstance(c, int) for c in counts) or sum(counts) != len(utterances):
        return None
    slices, at = [], 0
    for count in counts:
        slices.append(utterances[at : at + count])
        at += count
    return slices


def _write_pages_atomically(pages_path: Path, rows: list[dict[str, Any]]) -> None:
    """Replace ``pages.jsonl`` via a temp file, so a failure keeps the old pages."""
    tmp = pages_path.with_name(pages_path.name + ".tmp")
    try:
        tmp.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        os.replace(tmp, pages_path)
    finally:
        tmp.unlink(missing_ok=True)


def repaginate_sidecar(
    out_dir: Path,
    card_id: str,
    char_budget: int = _DEFAULT_CHAR_BUDGET,
    duration_budget_s: float = _DEFAULT_DURATION_BUDGET_S,
) -> str | None:
    """Re-paginate an existing sidecar in place, using stored utterances.

    Utterances come from the sidecar's ``utterances.jsonl``, or from inline
    ``meta["utterances"]`` for sidecars written before that file existed.
    Each row is paginated on its own, numbering continuing across rows, and
    its ``rows[].pages`` is recomputed.

    Returns ``None`` when the sidecar was rewritten, else the reason it was
    skipped. Idempotent: running twice produces the same result.
    """
    card_dir = out_dir / card_id
    meta_path = card_dir / "meta.json"

    meta = _read_meta(meta_path)
    utterances = read_utterances(card_dir, meta) if meta else []
    if not utterances:
        return "no utterances stored"
    rows_meta = [dict(r) for r in meta.get("rows", [])]
    slices = _row_slices(rows_meta, utterances)
    if slices is None:
        return "row boundaries were not recorded for this multi-row card"

    rows: list[dict[str, Any]] = []
    for i, chunk in enumerate(slices):
        new = build_pages_rows(
            chunk, start_page=len(rows) + 1,
            char_budget=char_budget, duration_budget_s=duration_budget_s,
        )
        rows.extend(new)
        if rows_meta:
            rows_meta[i]["pages"] = len(new)

    _write_pages_atomically(card_dir / "pages.jsonl", rows)

    if rows_meta:
        meta["rows"] = rows_meta
    meta["page_count"] = len(rows)
    meta["char_budget"] = char_budget
    meta["duration_budget_s"] = duration_budget_s
    meta["finished_at"] = datetime.now(UTC).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return None
