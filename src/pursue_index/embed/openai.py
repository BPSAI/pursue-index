"""OpenAI embedding adapter — seam for ``text-embedding-3-large``.

Stub for v1: the embed-stage plan calls Voyage-3 the default, with OpenAI
as the secondary option for A/B retrieval testing once we have a
methodology benchmark to compare them against. This module exists so the
pipeline's ``provider`` switch has a real second branch — the chat-stage
plan can flip it on without restructuring.

Construction is intentionally cheap (no SDK wiring) so callers that only
need to read ``usd_per_million_tokens`` for cost-cap math don't blow up.
The actual API call is what's a stub — ``embed_texts`` raises with a
guidance message pointing at the Voyage adapter.
"""

from __future__ import annotations

from pursue_index.embed.voyage import EmbedResult

DEFAULT_MODEL = "text-embedding-3-large"

# OpenAI's listed rate for text-embedding-3-large (Jan 2026 pricing). About
# 2× the Voyage-3 rate — hardcoding Voyage's $0.06 in the pipeline silently
# understates this provider's cost. Adapter owns the rate; pipeline reads it.
DEFAULT_USD_PER_MILLION_TOKENS = 0.13


class OpenAIAdapter:
    """Placeholder OpenAI embedding adapter.

    The seam exists so callers can refer to it without a try/except at the
    call site. Embedding-call wiring is deferred until we A/B Voyage-3 vs
    OpenAI in the benchmark stage; ``embed_texts`` raises a clean error
    pointing at the working alternative.
    """

    usd_per_million_tokens: float = DEFAULT_USD_PER_MILLION_TOKENS

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("OpenAIAdapter requires a non-empty api_key")
        self.model = model
        # Keep the key on the instance so future wiring is local — but don't
        # construct an SDK client yet. Construction is cheap and side-effect
        # free until the call site.
        self._api_key = api_key

    def embed_texts(
        self, texts: list[str], input_type: str = "document"
    ) -> EmbedResult:
        raise NotImplementedError(
            "OpenAI embedding adapter is a stub for v1; use the Voyage adapter "
            "(set PURSUE_EMBED_PROVIDER=voyage). Track wiring in "
            "`.paircoder/plans/embed-stage.md`."
        )
