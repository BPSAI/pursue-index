"""Shared ``--worklist`` helpers for the heavy ingest executors.

A *worklist* is a plain-text file of card_ids (one per line; blanks and
``#`` comments ignored) that scopes ``download``/``ocr``/``embed`` to a detected
tranche's genuinely-new cards instead of the full ~222-card corpus.
``pursue ingest run --from-diff`` writes this file from ``summarize_ingest_work``.

``download``/``ocr`` are manifest-driven, so ``apply_worklist`` subsets
``manifest.cards`` before the async fan-out. ``embed`` reads the OCR dir
directly, so it consumes ``worklist_card_ids`` as an ``only_cards`` filter.
A ``None`` path (flag omitted) is the full-corpus escape hatch — a no-op.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.scrape.types import Manifest


def read_worklist(path: Path) -> list[str]:
    """Card_ids from a worklist file: one per line, blanks and #-comments ignored."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            ids.append(stripped)
    return ids


def worklist_card_ids(path: Path | None) -> set[str] | None:
    """The worklist as a set, or ``None`` when no worklist (full-corpus escape hatch)."""
    if path is None:
        return None
    return set(read_worklist(path))


def apply_worklist(manifest: Manifest, path: Path | None) -> Manifest:
    """Subset ``manifest.cards`` to the worklist card_ids, preserving manifest order.

    A no-op returning the same object when ``path`` is ``None`` (the omitted-flag
    full-corpus escape hatch). Worklist ids absent from the manifest are ignored;
    un-listed cards are simply dropped (Class A / Class C cards were never scoped).
    """
    wanted = worklist_card_ids(path)
    if wanted is None:
        return manifest
    cards = [c for c in manifest.cards if c.card_id in wanted]
    return manifest.model_copy(update={"cards": cards})
