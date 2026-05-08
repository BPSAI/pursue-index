"""Ingest manifest + OCR output into Postgres.

Idempotent: cards are upserted by ``card_id``, pages are upserted by
``(card_id, page_number)``.
"""

from __future__ import annotations

from pursue_index import get_logger
from pursue_index.scrape.types import Manifest

log = get_logger(__name__)


def ingest_all(manifest: Manifest) -> None:
    # TODO(phase-4):
    #   - open SQLAlchemy session
    #   - upsert each Card from manifest
    #   - read OCR pages.jsonl and upsert Page rows
    #   - log counts: cards_upserted, pages_upserted
    log.warning("index.ingest.not_implemented", card_count=manifest.card_count)
    raise NotImplementedError("Index ingest arrives in phase 4 — see docs/architecture.md")
