"""OpenAI embedding adapter — seam for ``text-embedding-3-large``.

Stub for v1: the embed-stage plan calls Voyage-3 the default, with OpenAI
as the secondary option for A/B retrieval testing once we have a
methodology benchmark to compare them against. This module exists so the
pipeline's ``provider`` switch has a real second branch — the chat-stage
plan can flip it on without restructuring.
"""

from __future__ import annotations

from pursue_index.embed.voyage import EmbedResult

DEFAULT_MODEL = "text-embedding-3-large"


class OpenAIAdapter:
    """Placeholder OpenAI embedding adapter.

    Intentionally raises on construction — wiring the SDK is deferred until
    we A/B Voyage-3 vs OpenAI in the benchmark stage. The seam is here so
    callers can refer to it without a try/except at the call site.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("OpenAIAdapter requires a non-empty api_key")
        self.model = model
        raise NotImplementedError(
            "OpenAI embedding adapter is a stub for v1; use the Voyage adapter. "
            "Track wiring in `.paircoder/plans/embed-stage.md`."
        )

    def embed_texts(
        self, texts: list[str], input_type: str = "document"
    ) -> EmbedResult:  # pragma: no cover - unreachable until wired
        raise NotImplementedError
