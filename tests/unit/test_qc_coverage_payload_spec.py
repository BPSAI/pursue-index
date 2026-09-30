"""Coverage spec for ``qc-coverage.json``.

Pins that the gate catches the three ways the payload can lie: a card left
out, a card listed twice, and a status or provenance the sources no longer
support. Synthetic sources only; no corpus figures.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pursue_index.clean.qc.coverage import build_coverage
from pursue_index.embed import image_observations
from pursue_index.embed.image_observations import OBSERVATIONS_HEADER
from tests.support.payload_coverage import evaluate
from tests.support.payload_specs import (
    CLEAN_QC_BUNDLE,
    IMAGE_OBSERVATIONS,
    MANIFEST,
    PAGES,
    QC_COVERAGE,
    spec_for,
)
from tests.support.payload_specs_qc import shipped_qc_statuses

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OBSERVATIONS_HEADER_MODULE = image_observations.__name__

_SOURCES: dict[str, Any] = {
    MANIFEST: {
        "csv_sha256": "a" * 64,
        "fetched_at": "2026-09-01T00:00:00Z",
        "cards": [
            {"card_id": "pdf1", "asset_type": "PDF"},
            {"card_id": "pdf1", "asset_type": "PDF"},
            {"card_id": "aud1", "asset_type": "AUD"},
            {"card_id": "img1", "asset_type": "IMG"},
            {"card_id": "vid1", "asset_type": "VID"},
        ],
    },
    CLEAN_QC_BUNDLE: {
        "bundle_schema_version": 1,
        "generated_at": "2026-09-02T00:00:00+00:00",
        "runner_version": "0.2.0",
        "judge_model": "judge-x",
        "cards": [{"card_id": "pdf1", "page_count": 1}],
    },
    PAGES: [
        {"card_id": "pdf1", "page": 1, "text": "ocr"},
        {"card_id": "aud1", "page": 1, "text": "transcript"},
        {"card_id": "img1", "page": 1, "text": "description"},
    ],
    IMAGE_OBSERVATIONS: {"card_ids": ["img1"]},
}


def _fresh() -> dict[str, Any]:
    s = _SOURCES
    return build_coverage(s[MANIFEST], s[CLEAN_QC_BUNDLE], s[PAGES], s[IMAGE_OBSERVATIONS])


def _run(payload: Any, sources: dict[str, Any] = _SOURCES):
    docs = {**sources, QC_COVERAGE: payload}
    return evaluate(spec_for(QC_COVERAGE), lambda rel: docs[rel])


def test_a_freshly_built_payload_passes() -> None:
    result = _run(_fresh())
    assert result.ok
    distinct = {c["card_id"] for c in _SOURCES[MANIFEST]["cards"]}
    assert distinct <= {k[0] for k in shipped_qc_statuses(_fresh())}


def test_a_missing_card_fails() -> None:
    doc = _fresh()
    doc["cards"] = [c for c in doc["cards"] if c["card_id"] != "vid1"]
    assert _run(doc).missing == [("vid1", "no_text", ("VID",))]


def test_a_card_listed_twice_fails() -> None:
    doc = _fresh()
    doc["cards"].append(copy.deepcopy(doc["cards"][0]))
    assert _run(doc).extra == [(doc["cards"][0]["card_id"], "DUPLICATE", ())]


def test_a_status_the_sources_no_longer_support_fails() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[CLEAN_QC_BUNDLE]["cards"].append({"card_id": "aud1", "page_count": 1})
    result = _run(doc, sources)
    assert ("aud1", "judged", ("AUD",)) in result.missing
    assert ("aud1", "unverified_transcript", ("AUD",)) in result.extra


def test_a_payload_built_from_an_older_manifest_fails() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[MANIFEST]["csv_sha256"] = "b" * 64
    result = _run(doc, sources)
    assert [k[0] for k in result.extra] == ["generated_from"]


def test_a_hand_edited_count_fails() -> None:
    doc = _fresh()
    doc["status_counts"]["judged"] += 1
    assert not _run(doc).ok


def test_vision_text_pages_the_sources_no_longer_support_fail() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[PAGES].append(
        {"card_id": "pdf1", "page": 2, "text": f"{OBSERVATIONS_HEADER}, m]]\n\nphoto"}
    )
    result = _run(doc, sources)
    assert ("pdf1", "vision_text_pages", (2,)) in result.missing


def test_a_stale_judged_page_count_fails() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[PAGES].append({"card_id": "pdf1", "page": 2, "text": "re-OCR added this page"})
    result = _run(doc, sources)
    assert ("pdf1", "judged", ("PDF",)) in result.extra
    assert any(k[:2] == ("pdf1", "partially_judged") for k in result.missing)


def test_a_hand_edited_asset_type_fails() -> None:
    doc = _fresh()
    card = next(c for c in doc["cards"] if c["card_id"] == "vid1")
    card["asset_types"] = ["IMG"]
    result = _run(doc)
    assert result.missing == [("vid1", "no_text", ("VID",))]
    assert result.extra == [("vid1", "no_text", ("IMG",))]


def test_release_gate_fires_on_every_file_the_qc_gate_depends_on() -> None:
    """A change to any predicate module must trigger the gate that runs it."""
    spec = spec_for(QC_COVERAGE)
    modules = {
        spec.eligible.__module__,
        spec.shipped.__module__,
        build_coverage.__module__,
        OBSERVATIONS_HEADER_MODULE,
        "tests.support.payload_specs",
    }
    workflow = (REPO_ROOT / ".github/workflows/release-gate.yml").read_text()
    for mod in sorted(modules):
        root = "src/" if mod.startswith("pursue_index") else ""
        path = root + mod.replace(".", "/") + ".py"
        assert f'- "{path}"' in workflow, f"{path} missing from release-gate paths"
    assert '- "scripts/build_qc_coverage.py"' in workflow
