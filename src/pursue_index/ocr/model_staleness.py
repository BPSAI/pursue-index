"""Per-card model-staleness check over OCR page rows (R7C.16 / issue #171).

OCR rows record which engine produced them (``engine``) and, since R7C.16,
which model/build produced them (``model`` on an ``llm`` row, ``engine_version``
on a ``dots`` row — see ``ocr.runners``). A release needs to assert every
in-scope page was produced by the single currently operated LLM model: a card
whose ``llm`` rows disagree with each other, or agree on a model other than
the operated one, needs re-OCR before it ships.

``dots`` rows are the content-filter backstop, not a staleness signal in
their own right, so they never drive the flag — only ``llm`` rows are
compared against the operated model. A row written before R7C.16 carries
neither field; it is reported under the ``unknown`` sentinel, never raised
as an error.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.page_rows import latest_per_page
from pursue_index.scrape.types import CardMetadata, Manifest

__all__ = [
    "MODEL_UNKNOWN",
    "CardModelStatus",
    "build_staleness_report",
    "check_card_model_staleness",
    "row_model_label",
]

MODEL_UNKNOWN = "unknown"


def row_model_label(row: dict[str, Any]) -> str:
    """The model/version identity one OCR row carries, ``unknown`` if absent."""
    model = row.get("model")
    if model:
        return str(model)
    engine_version = row.get("engine_version")
    if engine_version:
        return str(engine_version)
    return MODEL_UNKNOWN


@dataclass(frozen=True)
class CardModelStatus:
    """One card's model-provenance verdict."""

    card_id: str
    row_models: tuple[str, ...]
    distinct_llm_models: tuple[str, ...]
    mixed_models: bool
    off_operated_model: bool

    @property
    def flagged(self) -> bool:
        return self.mixed_models or self.off_operated_model


def check_card_model_staleness(
    card_id: str, rows: Sequence[dict[str, Any]], operated_model: str
) -> CardModelStatus:
    """Flag ``card_id`` if its ``llm`` rows disagree, or agree off-model.

    Only each page's latest row counts. ``dots`` rows never trigger the flag — only the ``llm`` rows are
    compared against ``operated_model``. The ``unknown`` sentinel (an older
    sidecar missing both fields) is excluded from the comparison so a
    legacy row never reads as "off the operated model".
    """
    # The same rule the cleaned-page builder uses: a re-OCR'd page's older
    # rows are superseded and must not keep the card flagged.
    rows = latest_per_page(rows, card_id)
    row_models = tuple(row_model_label(r) for r in rows)
    llm_models = {row_model_label(r) for r in rows if r.get("engine") == "llm"}
    known_llm_models = llm_models - {MODEL_UNKNOWN}
    return CardModelStatus(
        card_id=card_id,
        row_models=row_models,
        distinct_llm_models=tuple(sorted(llm_models)),
        mixed_models=len(known_llm_models) > 1,
        off_operated_model=any(m != operated_model for m in known_llm_models),
    )


def _load_rows(pages_path: Path) -> list[dict[str, Any]]:
    if not pages_path.exists():
        return []
    return [json.loads(line) for line in pages_path.read_text().splitlines() if line.strip()]


def build_staleness_report(
    manifest: Manifest,
    ocr_dir_for: Callable[[CardMetadata], Path],
    operated_model: str,
) -> list[CardModelStatus]:
    """One ``CardModelStatus`` per manifest card that has OCR output."""
    statuses: list[CardModelStatus] = []
    for card in manifest.cards:
        rows = _load_rows(ocr_dir_for(card) / "pages.jsonl")
        if not rows:
            continue
        statuses.append(check_card_model_staleness(card.card_id, rows, operated_model))
    return statuses
