"""QC coverage over every manifest card (``pursue_index.clean.qc.coverage``).

The clean-QC bundle lists only the cards the page-level judge covered, so a
card outside it was simply absent. These tests pin the classification that
makes "not verified" explicit for every distinct card, on small fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pursue_index.clean.qc.coverage import (
    STATUSES,
    build_coverage,
    classify_cards,
)
from pursue_index.embed.image_observations import OBSERVATIONS_HEADER

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

VISION_TEXT = f"{OBSERVATIONS_HEADER}, model-x]]\n\nA photograph."


def _row(card_id: str, asset_type: str) -> dict:
    return {"card_id": card_id, "asset_type": asset_type}


def _page(card_id: str, page: int, text: str) -> dict:
    return {"card_id": card_id, "page": page, "text": text}


def _manifest(rows: list[dict]) -> dict:
    return {"csv_sha256": "c" * 64, "fetched_at": "2026-09-01T00:00:00+00:00", "cards": rows}


def _bundle(card_ids: list[str]) -> dict:
    return {
        "bundle_schema_version": 1,
        "generated_at": "2026-09-02T00:00:00+00:00",
        "runner_version": "0.2.0",
        "judge_model": "judge-x",
        "cards": [{"card_id": c, "page_count": 1} for c in card_ids],
    }


def _fixture() -> tuple[dict, dict, list[dict], dict]:
    manifest = _manifest(
        [
            _row("pdf-judged", "PDF"),
            _row("pdf-judged", "PDF"),  # repeated row: still one card
            _row("mixed", "PDF"),
            _row("mixed", "VID"),
            _row("aud", "AUD"),
            _row("aud-silent", "AUD"),
            _row("img", "IMG"),
            _row("img-bare", "IMG"),
            _row("vid", "VID"),
            _row("pdf-unjudged", "PDF"),
        ]
    )
    bundle = _bundle(["pdf-judged", "mixed"])
    pages = [
        _page("pdf-judged", 1, "OCR text"),
        _page("pdf-judged", 2, VISION_TEXT),
        _page("mixed", 1, "OCR text"),
        _page("aud", 1, "transcript"),
        _page("aud-silent", 1, "   "),
        _page("img", 1, VISION_TEXT),
        _page("pdf-unjudged", 1, "OCR text"),
    ]
    observations = {"card_ids": ["img", "pdf-judged"]}
    return manifest, bundle, pages, observations


def test_each_card_gets_the_status_its_sources_support() -> None:
    manifest, bundle, pages, observations = _fixture()
    statuses = classify_cards(manifest, bundle, pages, observations)
    assert statuses == {
        "pdf-judged": "judged",
        "mixed": "judged",
        "aud": "unverified_transcript",
        "aud-silent": "no_text",
        "img": "unverified_vision",
        "img-bare": "no_text",
        "vid": "no_text",
        "pdf-unjudged": "unverified_other",
    }
    assert set(statuses.values()) <= set(STATUSES)


def test_payload_lists_every_distinct_card_once_sorted() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations)
    ids = [c["card_id"] for c in doc["cards"]]
    assert ids == sorted({r["card_id"] for r in manifest["cards"]})
    assert doc["total_cards"] == len(ids)
    mixed = next(c for c in doc["cards"] if c["card_id"] == "mixed")
    assert mixed["asset_types"] == ["PDF", "VID"]


def test_counts_cover_every_status_and_sum_to_the_total() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations)
    assert list(doc["status_counts"]) == list(STATUSES)
    assert sum(doc["status_counts"].values()) == doc["total_cards"]
    for status, n in doc["status_counts"].items():
        assert n == sum(1 for c in doc["cards"] if c["status"] == status)


def test_unverified_other_is_listed_by_id() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations)
    assert doc["unverified_other"] == ["pdf-unjudged"]


def test_judged_pages_carrying_vision_text_are_named() -> None:
    """An image-only document page carries our vision description, not OCR;
    the page-level judge had no OCR to compare it against."""
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations)
    judged = next(c for c in doc["cards"] if c["card_id"] == "pdf-judged")
    assert judged["vision_text_pages"] == [2]
    assert doc["vision_text_pages_in_judged_cards"] == {"cards": 1, "pages": 1}
    others = [c for c in doc["cards"] if c["card_id"] != "pdf-judged"]
    assert all("vision_text_pages" not in c for c in others)


def test_generated_from_carries_only_input_provenance() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations)
    assert doc["generated_from"] == {
        "manifest_csv_sha256": manifest["csv_sha256"],
        "manifest_fetched_at": manifest["fetched_at"],
        "clean_qc_bundle": {
            "bundle_schema_version": 1,
            "generated_at": bundle["generated_at"],
            "runner_version": "0.2.0",
            "judge_model": "judge-x",
        },
    }


def test_a_bundle_card_outside_the_manifest_is_refused() -> None:
    manifest, bundle, pages, observations = _fixture()
    bundle["cards"].append({"card_id": "gone", "page_count": 1})
    with pytest.raises(ValueError, match="gone"):
        build_coverage(manifest, bundle, pages, observations)


def test_script_writes_deterministic_output(tmp_path: Path) -> None:
    import build_qc_coverage  # type: ignore[import-not-found]

    manifest, bundle, pages, observations = _fixture()
    paths = {}
    for name, doc in (
        ("manifest", manifest),
        ("bundle", bundle),
        ("pages", pages),
        ("observations", observations),
    ):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(doc))
    out = tmp_path / "qc-coverage.json"
    kwargs = dict(
        manifest_path=paths["manifest"],
        bundle_path=paths["bundle"],
        pages_path=paths["pages"],
        observations_path=paths["observations"],
        out_path=out,
    )
    build_qc_coverage.build(**kwargs)
    first = out.read_bytes()
    build_qc_coverage.build(**kwargs)
    assert out.read_bytes() == first
    assert json.loads(first)["status_counts"]["judged"] == 2
