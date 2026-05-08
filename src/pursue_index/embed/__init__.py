"""Embedding stage: page text → content-addressed vector file.

The chat-retrieval surface reads ``{data_root}/embeddings/{model_id}/`` —
``vectors.bin`` (contiguous float32) plus ``index.json`` (per-row mapping
back to ``card_id`` + page). Idempotent against the OCR output: a row
keyed by ``(card_id, page, model_id, text_sha)`` is only embedded once.
"""

from __future__ import annotations

__all__ = ["EmbedResult", "VoyageAdapter"]


def __getattr__(name: str):  # pragma: no cover - lazy import shim
    # Lazy import so ``import pursue_index.embed`` doesn't pull in voyageai
    # for callers that only need types.
    if name == "VoyageAdapter":
        from pursue_index.embed.voyage import VoyageAdapter

        return VoyageAdapter
    if name == "EmbedResult":
        from pursue_index.embed.voyage import EmbedResult

        return EmbedResult
    raise AttributeError(f"module 'pursue_index.embed' has no attribute {name!r}")
