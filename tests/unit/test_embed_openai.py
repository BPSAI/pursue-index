"""Tests for the OpenAI embedding adapter stub.

Construction must succeed so callers can read the documented rate (used by
the cost-cap math). The error must surface at the call site (``embed_texts``)
or at provider-routing time, not on import.
"""

from __future__ import annotations

import pytest


def test_openai_adapter_constructs_without_raising() -> None:
    """Construction is cheap and must not crash — that lets callers introspect
    ``usd_per_million_tokens`` even when they only resolve the provider seam.
    The actual SDK call is what's a stub for v1.
    """
    from pursue_index.embed.openai import OpenAIAdapter

    adapter = OpenAIAdapter(api_key="sk-test", model="text-embedding-3-large")
    assert adapter.model == "text-embedding-3-large"


def test_openai_adapter_exposes_openai_price_per_million_tokens() -> None:
    """text-embedding-3-large is ~$0.13/1M tokens per OpenAI's published rates.

    Hardcoding Voyage's $0.06 in the pipeline would understate the cost cap
    by ~2× for this provider — the regression this test guards against.
    """
    from pursue_index.embed.openai import OpenAIAdapter

    adapter = OpenAIAdapter(api_key="sk-test", model="text-embedding-3-large")
    # Allow a small drift if OpenAI moves the price; just make sure it's not
    # accidentally the Voyage rate.
    assert adapter.usd_per_million_tokens > 0.10


def test_openai_adapter_embed_texts_raises_until_wired() -> None:
    """The actual API call remains a stub — surface it cleanly, not as an
    AttributeError or surprise import error."""
    from pursue_index.embed.openai import OpenAIAdapter

    adapter = OpenAIAdapter(api_key="sk-test", model="text-embedding-3-large")
    with pytest.raises(NotImplementedError, match="(?i)stub|voyage"):
        adapter.embed_texts(["hello"])


def test_openai_adapter_requires_api_key() -> None:
    from pursue_index.embed.openai import OpenAIAdapter

    with pytest.raises(ValueError, match="api_key"):
        OpenAIAdapter(api_key="", model="text-embedding-3-large")
