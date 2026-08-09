"""Sidecar schema construction + validation for the vision stage.

The generator must emit sidecars in the SAME schema the frozen May/July
image-observations artifacts use, so the existing loader
(``embed.image_observations``) reads our fresh output unchanged. The
round-trip tests validate one real May sidecar and one real July sidecar,
then validate freshly-built output against the same model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.embed.image_observations import load_observation_text
from pursue_index.vision.sidecar import build_sidecar, validate_sidecar

FROZEN_DIR = Path("web/src/data/image-observations")
MAY_SIDECAR = FROZEN_DIR / "04b9179a7637d6ad.json"  # structured-only schema
JULY_SIDECAR = FROZEN_DIR / "4844321219e306af.json"  # prose + observations schema


def test_validates_real_may_sidecar() -> None:
    data = json.loads(MAY_SIDECAR.read_text())
    model = validate_sidecar(data)
    assert model.card_id == "04b9179a7637d6ad"
    assert model.our_pass["model"].startswith("claude-")
    assert model.pages[0].page == 1
    assert model.pages[0].observations  # structured-only still carries claims


def test_validates_real_july_sidecar() -> None:
    data = json.loads(JULY_SIDECAR.read_text())
    model = validate_sidecar(data)
    assert model.card_id == "4844321219e306af"
    assert {p.page for p in model.pages} == {81, 89}


def test_build_sidecar_output_validates_and_round_trips(tmp_path: Path) -> None:
    page = {
        "page": 1,
        "image_type": "black-and-white photograph",
        "description": "A disc-shaped object photographed face-on.",
        "visible_text": "",
        "observations": [
            {"claim": "The object is disc-shaped", "kind": "observation",
             "confidence": "high"},
        ],
    }
    sidecar = build_sidecar(
        card_id="freshcard",
        title="Fresh IMG",
        model="claude-opus-4-8",
        pages=[page],
    )
    # 1. Our output validates against the frozen schema.
    validate_sidecar(sidecar)
    assert sidecar["schema_version"] == 1
    assert sidecar["our_pass"]["model"] == "claude-opus-4-8"

    # 2. The existing loader reads it and renders searchable text (round-trip).
    (tmp_path / "freshcard.json").write_text(json.dumps(sidecar))
    (tmp_path / "index.json").write_text(
        json.dumps({"schema_version": 1, "card_ids": ["freshcard"]})
    )
    rendered = load_observation_text(tmp_path / "index.json")
    assert ("freshcard", 1) in rendered
    assert "disc-shaped object" in rendered[("freshcard", 1)]


def test_validate_rejects_missing_pages() -> None:
    with pytest.raises(Exception):
        validate_sidecar({"card_id": "x", "schema_version": 1, "our_pass": {}})


def test_validate_rejects_page_without_number() -> None:
    bad = {
        "card_id": "x",
        "schema_version": 1,
        "our_pass": {"model": "claude-opus-4-8"},
        "pages": [{"description": "no page number"}],
    }
    with pytest.raises(Exception):
        validate_sidecar(bad)
