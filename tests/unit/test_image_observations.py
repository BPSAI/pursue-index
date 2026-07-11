"""Tests for the image-observation text loader/renderer.

The loader turns operator-verified image-observation sidecars into a searchable
text blob keyed by ``(card_id, page)``. Callers inject that text for pages whose
base OCR is empty (genuinely image-only pages) so those pages carry our own
faithful description in both the search payload and the embed vectors, replacing
the retired Zhang VLM pass.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.image_observations import (
    OBSERVATIONS_HEADER,
    load_observation_text,
    render_page_text,
)


def _index(card_ids: list[str]) -> dict:
    return {"schema_version": 1, "card_ids": card_ids}


def _residual_sidecar(card_id: str, page: int) -> dict:
    return {
        "card_id": card_id,
        "our_pass": {"model": "claude-opus-4-8"},
        "pages": [
            {
                "page": page,
                "image_type": "black-and-white photograph",
                "description": "A photograph of a disc-shaped model object.",
                "visible_text": "",
                "observations": [
                    {"claim": "The object is disc-shaped", "kind": "observation",
                     "confidence": "high"},
                ],
            }
        ],
    }


def test_render_includes_header_description_and_claims() -> None:
    page = {
        "page": 1,
        "description": "A grassy field under a blue sky.",
        "visible_text": "",
        "observations": [{"claim": "A field is visible", "confidence": "high"}],
    }
    text = render_page_text(page, model="claude-opus-4-8")
    assert OBSERVATIONS_HEADER in text
    assert "claude-opus-4-8" in text
    assert "A grassy field under a blue sky." in text
    assert "- A field is visible" in text


def test_render_includes_visible_text_when_present() -> None:
    page = {"page": 1, "description": "A stamped page.",
            "visible_text": "TOP SECRET", "observations": []}
    text = render_page_text(page)
    assert 'Visible text: "TOP SECRET"' in text


def test_render_omits_empty_sections() -> None:
    page = {"page": 1, "description": "Only a description.",
            "visible_text": "", "observations": []}
    text = render_page_text(page)
    assert "Visible text" not in text
    assert "Observations" not in text


def test_render_tolerates_structured_only_schema() -> None:
    """Earlier helicopter-case sidecars have no description — only claims."""
    page = {"page": 1, "observations": [
        {"claim": "Reticle style is a small plus", "confidence": "high"}]}
    text = render_page_text(page)
    assert "- Reticle style is a small plus" in text
    assert OBSERVATIONS_HEADER in text


def test_load_returns_keyed_text(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps(_index(["cardA"])))
    (tmp_path / "cardA.json").write_text(json.dumps(_residual_sidecar("cardA", 5)))
    out = load_observation_text(tmp_path / "index.json")
    assert set(out.keys()) == {("cardA", 5)}
    assert "disc-shaped model object" in out[("cardA", 5)]


def test_load_multi_page_and_multi_card(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps(_index(["cardA", "cardB"])))
    side_a = _residual_sidecar("cardA", 81)
    side_a["pages"].append({"page": 89, "description": "second page",
                            "visible_text": "", "observations": []})
    (tmp_path / "cardA.json").write_text(json.dumps(side_a))
    (tmp_path / "cardB.json").write_text(json.dumps(_residual_sidecar("cardB", 6)))
    out = load_observation_text(tmp_path / "index.json")
    assert set(out.keys()) == {("cardA", 81), ("cardA", 89), ("cardB", 6)}


def test_load_missing_index_returns_empty(tmp_path: Path) -> None:
    assert load_observation_text(tmp_path / "nope.json") == {}


def test_load_malformed_index_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text("{not json}")
    assert load_observation_text(tmp_path / "index.json") == {}


def test_load_skips_card_without_sidecar(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps(_index(["ghost"])))
    assert load_observation_text(tmp_path / "index.json") == {}


def test_load_skips_malformed_sidecar(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(json.dumps(_index(["cardA"])))
    (tmp_path / "cardA.json").write_text("{broken")
    assert load_observation_text(tmp_path / "index.json") == {}
