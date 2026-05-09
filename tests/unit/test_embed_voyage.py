"""Tests for the Voyage-3 embedding adapter.

The actual SDK call is mocked at the ``voyageai.Client`` seam — these tests
run anywhere without a network or API key.
"""

from __future__ import annotations

from typing import Any

import pytest


def test_voyage_embed_texts_calls_sdk_and_returns_floats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pursue_index.embed import voyage

    captured: dict[str, Any] = {}

    class FakeResult:
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        total_tokens = 7

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        def embed(
            self,
            texts: list[str],
            model: str,
            input_type: str | None = None,
        ) -> FakeResult:
            captured["texts"] = list(texts)
            captured["model"] = model
            captured["input_type"] = input_type
            return FakeResult()

    monkeypatch.setattr(voyage, "_make_client", lambda api_key: FakeClient(api_key))

    adapter = voyage.VoyageAdapter(api_key="vk-test", model="voyage-3")
    result = adapter.embed_texts(["hello", "world"])

    assert result.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result.total_tokens == 7
    assert captured["texts"] == ["hello", "world"]
    assert captured["model"] == "voyage-3"
    assert captured["api_key"] == "vk-test"


def test_voyage_adapter_requires_api_key() -> None:
    from pursue_index.embed import voyage

    with pytest.raises(ValueError, match="api_key"):
        voyage.VoyageAdapter(api_key="", model="voyage-3")


def test_voyage_adapter_exposes_voyage_price_per_million_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each adapter is the source of truth for its own $/Mtok rate.

    Voyage-3 is documented at $0.06 / 1M tokens; the cost-cap math uses this
    when the CLI doesn't pass an override. Hardcoding the rate in the
    pipeline silently understated cost when the OpenAI adapter ships.
    """
    from pursue_index.embed import voyage

    monkeypatch.setattr(voyage, "_make_client", lambda api_key: object())
    adapter = voyage.VoyageAdapter(api_key="vk-test", model="voyage-3")
    assert adapter.usd_per_million_tokens == pytest.approx(0.06)
