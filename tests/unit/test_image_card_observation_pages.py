"""An image card's observations reach the payloads a reader searches.

An image card has no OCR output — there is no document to read — so it has no
card directory under the OCR root. Both consumers walk that root, so an
observation sidecar only becomes searchable if each of them also emits a page
for a card whose text comes from observations alone.

Both tests below go through the real consumer entry points: the embed page
walker and the static search payload builder.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pursue_index.embed.image_observations import load_observation_text
from pursue_index.embed.pipeline import iter_card_pages

REPO_ROOT = Path(__file__).resolve().parents[2]
SEARCH_DATA_SCRIPT = REPO_ROOT / "scripts" / "build_search_data.py"


def _load_search_data_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "build_search_data", SEARCH_DATA_SCRIPT
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage_observations(obs_dir: Path, card_id: str, claim: str) -> Path:
    obs_dir.mkdir(parents=True, exist_ok=True)
    (obs_dir / f"{card_id}.json").write_text(
        json.dumps(
            {
                "card_id": card_id,
                "schema_version": 1,
                "our_pass": {"model": "claude-opus-4-8"},
                "pages": [
                    {
                        "page": 1,
                        "description": "An infrared still of a hangar apron.",
                        "visible_text": "",
                        "observations": [{"claim": claim, "kind": "observation"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    index_path = obs_dir / "index.json"
    index_path.write_text(
        json.dumps({"schema_version": 1, "card_ids": [card_id]}), encoding="utf-8"
    )
    return index_path


def _stage_ocr_card(ocr_dir: Path, card_id: str, text: str) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    (card_dir / "pages.jsonl").write_text(
        json.dumps({"page": 1, "text": text}) + "\n", encoding="utf-8"
    )


def test_an_image_card_reaches_the_embed_page_rows(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    _stage_ocr_card(ocr_dir, "pdfcard", "Ordinary OCR text.")
    index_path = _stage_observations(tmp_path / "obs", "imgcard", "A parked airframe")

    rows = iter_card_pages(ocr_dir, load_observation_text(index_path))
    by_card = {r.card_id: r for r in rows}
    assert "imgcard" in by_card
    assert "A parked airframe" in by_card["imgcard"].text
    assert by_card["imgcard"].page == 1


def test_an_image_card_reaches_the_static_search_payload(tmp_path: Path) -> None:
    mod = _load_search_data_module()
    ocr_dir = tmp_path / "ocr"
    _stage_ocr_card(ocr_dir, "pdfcard", "Ordinary OCR text.")
    index_path = _stage_observations(tmp_path / "obs", "imgcard", "A parked airframe")

    manifest = tmp_path / "latest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_url": "https://www.war.gov/x.csv",
                "fetched_at": "2026-08-01T00:00:00Z",
                "csv_sha256": "0" * 64,
                "cards": [
                    {"card_id": "pdfcard", "title": "A document",
                     "asset_type": "PDF", "agency": "FBI",
                     "asset_url": "https://www.war.gov/a.pdf"},
                    {"card_id": "imgcard", "title": "An image",
                     "asset_type": "IMG", "agency": "FBI",
                     "asset_url": "https://www.war.gov/a.jpg"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "pages.json"
    assert mod.build(ocr_dir, manifest, out_path, index_path) == 0

    docs = json.loads(out_path.read_text(encoding="utf-8"))
    image_docs = [d for d in docs if d["card_id"] == "imgcard"]
    assert len(image_docs) == 1
    assert "A parked airframe" in image_docs[0]["text"]
    assert image_docs[0]["title"] == "An image"


def test_an_image_card_absent_from_the_manifest_stays_out_of_the_payload(
    tmp_path: Path,
) -> None:
    mod = _load_search_data_module()
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    index_path = _stage_observations(tmp_path / "obs", "imgcard", "A parked airframe")
    manifest = tmp_path / "latest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_url": "https://www.war.gov/x.csv",
                "fetched_at": "2026-08-01T00:00:00Z",
                "csv_sha256": "0" * 64,
                "cards": [],
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "pages.json"
    assert mod.build(ocr_dir, manifest, out_path, index_path) == 0
    assert json.loads(out_path.read_text(encoding="utf-8")) == []


def test_an_ocr_page_is_never_doubled_by_the_observation_path(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    _stage_ocr_card(ocr_dir, "imgcard", "Real OCR text for this card.")
    index_path = _stage_observations(tmp_path / "obs", "imgcard", "A parked airframe")

    rows = iter_card_pages(ocr_dir, load_observation_text(index_path))
    assert [(r.card_id, r.page) for r in rows] == [("imgcard", 1)]
    assert rows[0].text == "Real OCR text for this card."
