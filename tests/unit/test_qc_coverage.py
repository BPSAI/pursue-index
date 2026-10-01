"""QC coverage over every manifest card (``pursue_index.clean.qc.coverage``).

The clean-QC bundle lists only the cards the page-level judge covered, so a
card outside it was simply absent. These tests pin the classification that
makes "not verified" explicit for every distinct card, on small fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pursue_index.clean.qc.coverage import (
    STATUSES,
    build_coverage,
    classify_cards,
)
from pursue_index.embed.image_observations import OBSERVATIONS_HEADER

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_qc_coverage  # type: ignore[import-not-found] # noqa: E402

VISION_TEXT = f"{OBSERVATIONS_HEADER}, model-x]]\n\nA photograph."


def _row(card_id: str, asset_type: str) -> dict:
    return {"card_id": card_id, "asset_type": asset_type}


def _page(card_id: str, page: int, text: str) -> dict:
    return {"card_id": card_id, "page": page, "text": text}


def _manifest(rows: list[dict]) -> dict:
    return {"csv_sha256": "c" * 64, "fetched_at": "2026-09-01T00:00:00+00:00", "cards": rows}


def _bundle(page_counts: dict[str, int]) -> dict:
    return {
        "bundle_schema_version": 1,
        "generated_at": "2026-09-02T00:00:00+00:00",
        "runner_version": "0.2.0",
        "judge_model": "judge-x",
        "cards": [{"card_id": c, "page_count": n} for c, n in page_counts.items()],
    }


def _obs_text(observations: dict) -> dict[tuple[str, int], str]:
    """What observation_text_for renders when every listed sidecar is sound."""
    return {(cid, 1): VISION_TEXT for cid in observations["card_ids"]}


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
    bundle = _bundle({"pdf-judged": 2, "mixed": 1})
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
    statuses = classify_cards(manifest, bundle, pages, observations, _obs_text(observations))
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


def test_a_card_whose_pages_changed_after_the_sweep_is_only_partially_judged() -> None:
    """The bundle's page_count is the card's page rows at sweep time; a later
    re-OCR that adds a page leaves that page unjudged."""
    manifest, bundle, pages, observations = _fixture()
    pages.append(_page("mixed", 2, "page added by a re-OCR"))
    assert "partially_judged" in STATUSES
    assert classify_cards(manifest, bundle, pages, observations, _obs_text(observations))["mixed"] == "partially_judged"
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    mixed = next(c for c in doc["cards"] if c["card_id"] == "mixed")
    assert (mixed["judged_pages"], mixed["current_pages"]) == (1, 2)
    assert doc["status_counts"]["partially_judged"] == 1
    judged = next(c for c in doc["cards"] if c["card_id"] == "pdf-judged")
    assert "judged_pages" not in judged


def test_an_empty_ocr_page_still_counts_toward_the_judged_page_count() -> None:
    """The producer judges every cleanup row, including empty-input pages."""
    manifest, bundle, pages, observations = _fixture()
    pages.append(_page("mixed", 2, ""))
    bundle["cards"][1]["page_count"] = 2
    assert classify_cards(manifest, bundle, pages, observations, _obs_text(observations))["mixed"] == "judged"


def test_payload_lists_every_distinct_card_once_sorted() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    ids = [c["card_id"] for c in doc["cards"]]
    assert ids == sorted({r["card_id"] for r in manifest["cards"]})
    assert doc["total_cards"] == len(ids)
    mixed = next(c for c in doc["cards"] if c["card_id"] == "mixed")
    assert mixed["asset_types"] == ["PDF", "VID"]


def test_counts_cover_every_status_and_sum_to_the_total() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    assert list(doc["status_counts"]) == list(STATUSES)
    assert sum(doc["status_counts"].values()) == doc["total_cards"]
    for status, n in doc["status_counts"].items():
        assert n == sum(1 for c in doc["cards"] if c["status"] == status)


def test_unverified_other_is_listed_by_id() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    assert doc["unverified_other"] == ["pdf-unjudged"]
    assert doc["unverified_other_reasons"] == {
        "pdf-unjudged": "carries text that no QC status covers"
    }


def test_judged_pages_carrying_vision_text_are_named() -> None:
    """An image-only document page carries our vision description, not OCR;
    the page-level judge had no OCR to compare it against."""
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    judged = next(c for c in doc["cards"] if c["card_id"] == "pdf-judged")
    assert judged["vision_text_pages"] == [2]
    assert doc["vision_text_pages_in_judged_cards"] == {"cards": 1, "pages": 1}
    others = [c for c in doc["cards"] if c["card_id"] != "pdf-judged"]
    assert all("vision_text_pages" not in c for c in others)


def test_generated_from_carries_only_input_provenance() -> None:
    manifest, bundle, pages, observations = _fixture()
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
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


def test_a_bundle_card_outside_the_manifest_is_listed_not_counted() -> None:
    """A card that left the corpus must not block a rebuild, nor be counted."""
    manifest, bundle, pages, observations = _fixture()
    bundle["cards"].append({"card_id": "gone", "page_count": 1})
    doc = build_coverage(manifest, bundle, pages, observations, _obs_text(observations))
    assert doc["bundle_cards_not_in_manifest"] == ["gone"]
    assert "gone" not in {c["card_id"] for c in doc["cards"]}


def test_script_writes_deterministic_output(tmp_path: Path) -> None:
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


def test_a_listed_card_without_a_readable_sidecar_is_not_a_vision_description(
    tmp_path: Path,
) -> None:
    """Index membership is not a description: the card counts as described
    only when its sidecar renders text, through the loader the site uses."""
    manifest = _manifest(
        [_row("img-ok", "IMG"), _row("img-missing", "IMG"), _row("img-bad", "IMG")]
    )
    obs_dir = tmp_path / "image-observations"
    obs_dir.mkdir()
    index = obs_dir / "index.json"
    index.write_text(json.dumps({"card_ids": ["img-ok", "img-missing", "img-bad"]}))
    (obs_dir / "img-ok.json").write_text(
        json.dumps({"pages": [{"page": 1, "description": "A photograph of a ridge."}]})
    )
    (obs_dir / "img-bad.json").write_text("{not json")
    paths = {}
    for name, doc in (("manifest", manifest), ("bundle", _bundle({})), ("pages", [])):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(doc))
    out = tmp_path / "qc-coverage.json"
    doc = build_qc_coverage.build(
        manifest_path=paths["manifest"],
        bundle_path=paths["bundle"],
        pages_path=paths["pages"],
        observations_path=index,
        out_path=out,
    )
    statuses = {c["card_id"]: c["status"] for c in doc["cards"]}
    assert statuses == {
        "img-ok": "unverified_vision",
        "img-missing": "unverified_other",
        "img-bad": "unverified_other",
    }
    assert doc["unverified_other"] == ["img-bad", "img-missing"]
    assert set(doc["unverified_other_reasons"]) == {"img-bad", "img-missing"}
    assert all("sidecar" in r for r in doc["unverified_other_reasons"].values())
