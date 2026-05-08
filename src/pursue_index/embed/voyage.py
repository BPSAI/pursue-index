"""Voyage-3 embedding adapter.

Exposes ``VoyageAdapter.embed_texts(texts) -> EmbedResult`` mirroring the
shape used by other engine seams in this project. The Voyage SDK is
imported lazily on first use so ``pursue_index.embed`` can be imported
without the optional ``voyageai`` dep installed (the CLI lazy-imports
the pipeline anyway).

Voyage's `voyage-3` model is the default per the embed-stage plan:
strong document-retrieval benchmarks, $0.06 / 1M tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pursue_index import get_logger

log = get_logger(__name__)

DEFAULT_MODEL = "voyage-3"


@dataclass(frozen=True)
class EmbedResult:
    """Output of a single ``embed_texts`` call."""

    vectors: list[list[float]]
    total_tokens: int


def _make_client(api_key: str) -> Any:
    """Construct the Voyage SDK client. Indirected so tests can stub it."""
    import voyageai  # local import — keeps voyageai an optional runtime dep

    return voyageai.Client(api_key=api_key)


class VoyageAdapter:
    """Thin adapter around ``voyageai.Client.embed``.

    ``input_type="document"`` is the right setting for indexing pages — the
    chat surface should embed user queries with ``input_type="query"``,
    which we'll wire when the chat backend lands.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("VoyageAdapter requires a non-empty api_key")
        self.model = model
        self._client = _make_client(api_key)

    def embed_texts(
        self, texts: list[str], input_type: str = "document"
    ) -> EmbedResult:
        """Embed a batch of texts. Returns the parallel list of vectors."""
        if not texts:
            return EmbedResult(vectors=[], total_tokens=0)
        result = self._client.embed(texts, model=self.model, input_type=input_type)
        return EmbedResult(
            vectors=list(result.embeddings),
            total_tokens=int(result.total_tokens),
        )
