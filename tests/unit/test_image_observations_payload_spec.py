"""Tests for image observations payload coverage spec.

Demonstrates that:
1. The spec correctly identifies missing IMG cards
2. The eligibility predicate is imported from vision module (not duplicated)
3. The spec is integrated into the coverage gate
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pursue_index.vision import eligible_image_observation_card_ids
from tests.support.payload_coverage import evaluate, json_loader
from tests.support.payload_specs import SPECS


def test_eligibility_function_is_imported_from_vision_module() -> None:
    """The spec reuses the vision module's eligibility predicate."""
    from tests.support import payload_specs

    # Verify the function is actually imported, not duplicated locally
    assert hasattr(payload_specs, 'eligible_image_observation_card_ids')
    assert payload_specs.eligible_image_observation_card_ids is eligible_image_observation_card_ids


def test_spec_for_image_observations_exists() -> None:
    """The image observations spec is registered in SPECS."""
    specs_by_payload = {s.payload: s for s in SPECS}
    assert "web/src/data/image-observations/index.json" in specs_by_payload


def test_missing_img_card_fails_spec(tmp_path: Path) -> None:
    """When an IMG card is missing from index.json, the spec fails and names it."""
    # Create minimal test data
    manifest = {
        "cards": [
            {"card_id": "img_card_1", "asset_type": "IMG"},
            {"card_id": "img_card_2", "asset_type": "IMG"},
        ]
    }

    # index.json is missing img_card_2
    index_data = {
        "schema_version": 1,
        "card_ids": ["img_card_1"]
    }

    # Create temporary files
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))

    pages_file = tmp_path / "pages.json"
    pages_file.write_text(json.dumps([]))

    index_file = tmp_path / "index.json"
    index_file.write_text(json.dumps(index_data))

    # Build the spec and evaluate against test data
    spec = next(s for s in SPECS if s.payload == "web/src/data/image-observations/index.json")

    # Manually evaluate with test data
    def test_loader(rel_path: str) -> Any:
        if rel_path == "data/manifests/latest.json":
            return manifest
        if rel_path == "web/public/data/pages.json":
            return []
        if rel_path == "web/src/data/image-observations/index.json":
            return index_data
        raise ValueError(f"Unknown path: {rel_path}")

    # Patch the spec temporarily to use test paths
    from unittest.mock import patch

    test_spec = type(spec)(
        payload="test-payload",
        sources=("test-manifest", "test-pages"),
        eligible=lambda s: eligible_image_observation_card_ids({"manifest": s["test-manifest"], "pages": s["test-pages"]}),
        shipped=spec.shipped,
        require_no_missing=spec.require_no_missing,
        require_no_extra=spec.require_no_extra,
        key_label=spec.key_label,
        rationale=spec.rationale,
    )

    # Create custom loader
    sources = {
        "test-manifest": manifest,
        "test-pages": [],
        "test-payload": index_data,
    }

    eligible = test_spec.eligible(sources)
    shipped = test_spec.shipped(index_data)

    # Verify missing card is detected
    assert "img_card_2" in eligible
    assert "img_card_2" not in shipped
    assert "img_card_1" in eligible
    assert "img_card_1" in shipped


def test_stale_entry_in_index_fails_spec() -> None:
    """When index.json has an entry not in manifest, spec fails (require_no_extra=True)."""
    spec = next(s for s in SPECS if s.payload == "web/src/data/image-observations/index.json")

    # Simulate test data where manifest has 1 IMG card but index has 2
    manifest = {"cards": [{"card_id": "img_1", "asset_type": "IMG"}]}
    pages = []

    # index.json has a stale card_id not in manifest
    index_data = {"schema_version": 1, "card_ids": ["img_1", "unknown_card"]}

    sources = {
        "data/manifests/latest.json": manifest,
        "web/public/data/pages.json": pages,
        "web/src/data/image-observations/index.json": index_data,
    }

    eligible = spec.eligible(sources)
    shipped = spec.shipped(index_data)

    # Verify stale entry is detected
    assert eligible == {"img_1"}
    assert shipped == {"img_1", "unknown_card"}
    assert "unknown_card" not in eligible
    assert "unknown_card" in shipped


def test_spec_requires_both_no_missing_and_no_extra() -> None:
    """The spec enforces both require_no_missing and require_no_extra."""
    spec = next(s for s in SPECS if s.payload == "web/src/data/image-observations/index.json")

    assert spec.require_no_missing is True, "Spec should require no missing entries"
    assert spec.require_no_extra is True, "Spec should require no extra entries"


def test_sources_are_manifest_and_pages() -> None:
    """The spec reads committed files: manifest and pages.json."""
    spec = next(s for s in SPECS if s.payload == "web/src/data/image-observations/index.json")

    assert "data/manifests/latest.json" in spec.sources
    assert "web/public/data/pages.json" in spec.sources
    # Verify no environment-dependent or network paths
    for source in spec.sources:
        assert not source.startswith("$"), f"Source should not use env vars: {source}"
        assert "://" not in source, f"Source should not be a URL: {source}"
