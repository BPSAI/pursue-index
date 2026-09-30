"""Coverage spec for ``qc-coverage.json``.

Pins that the gate catches the three ways the payload can lie: a card left
out, a card listed twice, and a status or provenance the sources no longer
support. Synthetic sources only; no corpus figures.
"""

from __future__ import annotations

import copy
from typing import Any

from pursue_index.clean.qc.coverage import build_coverage
from tests.support.payload_coverage import evaluate
from tests.support.payload_specs import (
    CLEAN_QC_BUNDLE,
    IMAGE_OBSERVATIONS,
    MANIFEST,
    PAGES,
    QC_COVERAGE,
    spec_for,
)

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
    assert result.shipped_count == len(distinct) + 1  # + the provenance key


def test_a_missing_card_fails() -> None:
    doc = _fresh()
    doc["cards"] = [c for c in doc["cards"] if c["card_id"] != "vid1"]
    assert _run(doc).missing == [("vid1", "no_text")]


def test_a_card_listed_twice_fails() -> None:
    doc = _fresh()
    doc["cards"].append(copy.deepcopy(doc["cards"][0]))
    assert _run(doc).extra == [(doc["cards"][0]["card_id"], "DUPLICATE")]


def test_a_status_the_sources_no_longer_support_fails() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[CLEAN_QC_BUNDLE]["cards"].append({"card_id": "aud1", "page_count": 1})
    result = _run(doc, sources)
    assert ("aud1", "judged") in result.missing
    assert ("aud1", "unverified_transcript") in result.extra


def test_a_payload_built_from_an_older_manifest_fails() -> None:
    doc = _fresh()
    sources = copy.deepcopy(_SOURCES)
    sources[MANIFEST]["csv_sha256"] = "b" * 64
    result = _run(doc, sources)
    assert not result.ok
    assert any(k[0] == "generated_from" for k in result.extra)
