"""Test ``scripts/build_search_data.py``.

The external alex-zhang42 augment corpus was retired 2026-07-11. The build now
emits plain OCR text, except that genuinely image-only pages (zero base OCR)
whose ``(card_id, page)`` is in the image-observations index receive our own
operator-reviewed vision-pass description — kept byte-identical to what the
embed run hashes for that page so keyword and vector retrieval stay in parity.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_search_data.py"


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_search_data", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage_card(
    ocr_dir: Path,
    card_id: str,
    pages: list[tuple[int, str]],
    status: str = "ok",
) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": status}))
    with (card_dir / "pages.jsonl").open("w") as fh:
        for page, text in pages:
            fh.write(json.dumps({"page": page, "text": text}) + "\n")


def _stage_manifest(manifests_dir: Path, cards: list[dict]) -> None:
    manifests_dir.mkdir(parents=True, exist_ok=True)
    full_cards = [
        {
            "card_id": c["card_id"],
            "title": c["title"],
            "asset_type": c.get("asset_type", "PDF"),
            "agency": c.get("agency", "FBI"),
            "asset_url": c["asset_url"],
        }
        for c in cards
    ]
    (manifests_dir / "latest.json").write_text(
        json.dumps(
            {
                "source_url": "https://www.war.gov/x.csv",
                "fetched_at": "2026-05-08T00:00:00Z",
                "csv_sha256": "deadbeef",
                "cards": full_cards,
            }
        )
    )


def _stage_obs_index(
    obs_dir: Path, card_id: str, page: int, description: str
) -> Path:
    """Write an image-observations index + sidecar; return the index path."""
    obs_dir.mkdir(parents=True)
    (obs_dir / "index.json").write_text(
        json.dumps({"schema_version": 1, "card_ids": [card_id]})
    )
    (obs_dir / f"{card_id}.json").write_text(
        json.dumps(
            {
                "card_id": card_id,
                "our_pass": {"model": "claude-opus-4-8"},
                "pages": [
                    {
                        "page": page,
                        "description": description,
                        "visible_text": "",
                        "observations": [],
                    }
                ],
            }
        )
    )
    return obs_dir / "index.json"


_CARD = "ff30c985595153f3"
_URL = "https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf"


def test_run_emits_plain_ocr_text(tmp_path: Path) -> None:
    """The default payload is plain un-augmented OCR text — no marker blocks."""
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, _CARD, [(1, "OCR text page one.")])
    _stage_manifest(tmp_path / "manifests", [{"card_id": _CARD, "title": "T",
                                              "asset_url": _URL}])

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert len(docs) == 1
    assert docs[0]["text"] == "OCR text page one."
    assert "IMAGE-DESCRIPTIONS" not in docs[0]["text"]


def test_card_not_in_manifest_is_skipped(tmp_path: Path) -> None:
    """A card with OCR on disk but absent from the manifest must not enter the
    public search index — else it's a search hit with no page."""
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, _CARD, [(1, "kept page")])
    _stage_card(ocr_dir, "dead0000deadbeef", [(1, "removed-card page")])
    _stage_manifest(tmp_path / "manifests", [{"card_id": _CARD, "title": "T",
                                              "asset_url": _URL}])

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert [d["card_id"] for d in docs] == [_CARD]


def test_image_only_page_gets_vision_pass_text(tmp_path: Path) -> None:
    """An empty-OCR page whose card is in the image-observations index receives
    our vision-pass description, marked with the IMAGE-OBSERVATIONS header."""
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, _CARD, [(1, "")])
    _stage_manifest(tmp_path / "manifests", [{"card_id": _CARD, "title": "T",
                                              "asset_url": _URL}])
    obs_index = _stage_obs_index(
        tmp_path / "obs", _CARD, 1, "A photograph of a metallic disc."
    )

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        image_obs_index=obs_index,
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert len(docs) == 1
    text = docs[0]["text"]
    assert "IMAGE-OBSERVATIONS" in text
    assert "A photograph of a metallic disc." in text


def test_image_only_page_blank_without_obs_index(tmp_path: Path) -> None:
    """Without an obs index, an empty-OCR page falls through as empty text —
    the retirement did not silently invent content for it."""
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, _CARD, [(1, "")])
    _stage_manifest(tmp_path / "manifests", [{"card_id": _CARD, "title": "T",
                                              "asset_url": _URL}])

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        image_obs_index=tmp_path / "nonexistent.json",
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert docs[0]["text"] == ""
