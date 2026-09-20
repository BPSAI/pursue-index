"""Coverage spec for the image-observations index.

The spec's eligible set comes from the vision stage's own selection
(``select_eligible``), never from a second copy of the rule, and never from
``pages.json`` — which is itself built from the index, so deriving eligibility
from it would be circular.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.vision.eligibility import select_eligible
from tests.support import payload_specs
from tests.support.payload_coverage import evaluate, json_loader
from tests.support.payload_specs import IMAGE_OBSERVATIONS, MANIFEST, PAGES, SPECS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = next(s for s in SPECS if s.payload == IMAGE_OBSERVATIONS)


def _card(card_id: str, asset_type: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title=card_id,
        asset_type=asset_type,
        agency="FBI",
        asset_url=f"https://media.defense.gov/{card_id}",
        asset_filename=f"{card_id}.bin",
    )


def _manifest_dict(cards: list[CardMetadata]) -> dict:
    manifest = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    return manifest.model_dump(mode="json")


def _write_ocr(ocr_dir: Path, card_id: str, texts: list[str]) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    rows = [{"page": n, "text": text} for n, text in enumerate(texts, start=1)]
    (card_dir / "pages.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_spec_uses_the_vision_stage_predicate() -> None:
    assert payload_specs.select_eligible is select_eligible
    assert not hasattr(payload_specs, "eligible_image_observation_card_ids")


def test_spec_does_not_derive_eligibility_from_pages_json() -> None:
    assert PAGES not in SPEC.sources
    assert SPEC.sources == (MANIFEST,)


def test_eligible_set_follows_asset_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payload_specs, "_vision_ocr_dir", lambda: tmp_path)
    _write_ocr(tmp_path, "pdf_blank", ["text", "  "])
    _write_ocr(tmp_path, "pdf_text", ["text"])
    # A non-PDF card with an empty OCR page must not be eligible.
    _write_ocr(tmp_path, "vid_blank", [""])
    manifest = _manifest_dict(
        [
            _card("img1", "IMG"),
            _card("pdf_blank", "PDF"),
            _card("pdf_text", "PDF"),
            _card("vid_blank", "VID"),
            _card("aud1", "AUD"),
        ]
    )
    assert SPEC.eligible({MANIFEST: manifest}) == {"img1", "pdf_blank"}


def test_missing_eligible_card_fails_the_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payload_specs, "_vision_ocr_dir", lambda: tmp_path)
    manifest = _manifest_dict([_card("img1", "IMG"), _card("img2", "IMG")])
    docs = {MANIFEST: manifest, IMAGE_OBSERVATIONS: {"card_ids": ["img1"]}}
    result = evaluate(SPEC, docs.__getitem__)
    assert result.missing == ["img2"]
    assert not result.ok


def test_spec_passes_on_the_shipped_index() -> None:
    result = evaluate(SPEC, json_loader(REPO_ROOT))
    assert result.ok, result.missing
    assert result.eligible_count > 0


def test_spec_fails_when_one_eligible_id_is_removed() -> None:
    load = json_loader(REPO_ROOT)
    index = copy.deepcopy(load(IMAGE_OBSERVATIONS))
    victim = sorted(SPEC.eligible({MANIFEST: load(MANIFEST)}))[0]
    index["card_ids"].remove(victim)
    docs = {MANIFEST: load(MANIFEST), IMAGE_OBSERVATIONS: index}
    result = evaluate(SPEC, docs.__getitem__)
    assert result.missing == [victim]


def test_shipped_index_names_only_image_or_pdf_manifest_cards() -> None:
    """Extras cannot be judged against OCR output CI does not have, but every
    listed card must still be an IMG or PDF card in the manifest."""
    load = json_loader(REPO_ROOT)
    types = {}
    for card in load(MANIFEST)["cards"]:
        types.setdefault(card["card_id"], set()).add(card["asset_type"])
    for card_id in load(IMAGE_OBSERVATIONS)["card_ids"]:
        assert types.get(card_id, set()) & {"IMG", "PDF"}, card_id
