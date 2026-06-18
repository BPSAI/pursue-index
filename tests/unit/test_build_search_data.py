"""Test ``scripts/build_search_data.py`` augmentation propagation.

Per vaivora cross-cutting blocker #1: when an augmented embed run was
done (``embed/{model}/index.json`` carries ``augmented_by``), the
deployed ``pages.json`` must include the same ``[[IMAGE-DESCRIPTIONS
via ...]]`` block in each page's ``text`` field. Otherwise the chat
prompt, citation snippets, and user-facing surface all see un-augmented
OCR while the vectors retrieve against augmented text.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

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
    # Fill in fields required by the Manifest pydantic model used by the
    # atlas-join path (load_manifest validates the JSON shape).
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


def _stage_index(
    embeddings_dir: Path, model_id: str, augmented_by: dict | None = None
) -> None:
    """Drop a minimal ``index.json`` whose presence (with ``augmented_by``)
    triggers the augmentation lookup path in the build script.
    """
    out = embeddings_dir / model_id
    out.mkdir(parents=True)
    payload: dict = {
        "model_id": model_id,
        "dim": 4,
        "n": 0,
        "pages": [],
    }
    if augmented_by is not None:
        payload["augmented_by"] = augmented_by
    (out / "index.json").write_text(json.dumps(payload))


def _stage_corpus(
    external_dir: Path, body: str, name: str = "alex-zhang42-corpus.jsonl"
) -> Path:
    import hashlib

    external_dir.mkdir(parents=True)
    corpus = external_dir / name
    corpus.write_text(body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    (external_dir / f"{Path(name).stem}.sha256").write_text(
        f"{digest}  {name}\n"
    )
    return corpus


def test_unaugmented_run_emits_plain_ocr_text(tmp_path: Path) -> None:
    """Without ``augmented_by``, the search payload is the existing
    un-augmented shape — backward compatible with all prior runs.
    """
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(
        ocr_dir, "ff30c985595153f3", [(1, "OCR text page one.")]
    )
    _stage_manifest(
        tmp_path / "manifests",
        [
            {
                "card_id": "ff30c985595153f3",
                "title": "T",
                "asset_url": (
                    "https://www.war.gov/medialink/ufo/release_1/"
                    "059uap00011.pdf"
                ),
            }
        ],
    )

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        embeddings_root=tmp_path / "embeddings",
        embed_model="voyage-3",
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert len(docs) == 1
    assert docs[0]["text"] == "OCR text page one."
    assert "IMAGE-DESCRIPTIONS" not in docs[0]["text"]


def test_card_not_in_manifest_is_skipped(tmp_path: Path) -> None:
    """A card with OCR on disk but absent from the manifest (e.g. an
    upstream-removed re-encode whose live successor carries the content) must
    NOT enter the public search index — else it's a search hit with no page."""
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, "ff30c985595153f3", [(1, "kept page")])
    _stage_card(ocr_dir, "dead0000deadbeef", [(1, "removed-card page")])
    _stage_manifest(
        tmp_path / "manifests",
        [
            {
                "card_id": "ff30c985595153f3",
                "title": "T",
                "asset_url": "https://www.war.gov/medialink/ufo/x.pdf",
            }
        ],
    )

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        embeddings_root=tmp_path / "embeddings",
        embed_model="voyage-3",
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert [d["card_id"] for d in docs] == ["ff30c985595153f3"]


def _stage_one_card_setup(tmp_path: Path) -> Path:
    """Stage a card + manifest + augmented index.json + corpus.

    Returns the corpus path so callers can pass it through to ``build()``.
    """
    ocr_dir = tmp_path / "ocr"
    _stage_card(
        ocr_dir, "ff30c985595153f3", [(1, "OCR text page one.")]
    )
    _stage_manifest(
        tmp_path / "manifests",
        [
            {
                "card_id": "ff30c985595153f3",
                "title": "T",
                "asset_url": (
                    "https://www.war.gov/medialink/ufo/release_1/"
                    "059uap00011.pdf"
                ),
            }
        ],
    )
    _stage_index(
        tmp_path / "embeddings", "voyage-3",
        {
            "dataset": "alex-zhang42/ufo-pursue-open-atlas",
            "revision": "rev",
            "sha256": "x" * 64,
        },
    )
    return _stage_corpus(
        tmp_path / "external",
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["A metallic disc."]}\n',
    )


def test_augmented_run_appends_image_descriptions_block(tmp_path: Path) -> None:
    """When ``index.json`` carries ``augmented_by``, the build script must
    apply the same atlas_join lookup ``embed/store.py`` used and append
    the ``[[IMAGE-DESCRIPTIONS via ...]]`` block to every matching page.

    This is the only path by which the marker reaches ``pages.json`` and
    therefore the chat prompt + citation snippets.
    """
    from pursue_index.embed.store import AUGMENT_BLOCK_HEADER

    out_path = tmp_path / "pages.json"
    corpus = _stage_one_card_setup(tmp_path)

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=tmp_path / "ocr",
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        embeddings_root=tmp_path / "embeddings",
        embed_model="voyage-3",
        augment_corpus=corpus,
        augment_miss_rate_threshold=0.5,
    )
    assert rc == 0
    docs = json.loads(out_path.read_text())
    assert len(docs) == 1
    text = docs[0]["text"]
    assert "OCR text page one." in text
    assert AUGMENT_BLOCK_HEADER in text
    assert "- A metallic disc." in text


def _stage_one_card_manifest(tmp_path: Path) -> None:
    """Helper: a manifest pointing at the single fixture card_id."""
    _stage_manifest(
        tmp_path / "manifests",
        [
            {
                "card_id": "ff30c985595153f3",
                "title": "T",
                "asset_url": (
                    "https://www.war.gov/medialink/ufo/release_1/"
                    "059uap00011.pdf"
                ),
            }
        ],
    )


def _stage_augmented_by(tmp_path: Path) -> dict:
    """Helper: write the embed index with augmentation provenance."""
    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "rev",
        "sha256": "x" * 64,
    }
    _stage_index(tmp_path / "embeddings", "voyage-3", augmented_by)
    return augmented_by


def test_augmented_run_skips_pages_without_matching_tags(tmp_path: Path) -> None:
    """A page whose ``(card_id, page)`` is not in the atlas join must
    pass through un-augmented even when the run is otherwise augmented.
    """
    from pursue_index.embed.store import AUGMENT_BLOCK_HEADER

    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    # Two pages on the same card; only page 1 has a tag.
    _stage_card(
        ocr_dir, "ff30c985595153f3",
        [(1, "page one"), (2, "page two")],
    )
    _stage_one_card_manifest(tmp_path)
    _stage_augmented_by(tmp_path)
    corpus = _stage_corpus(
        tmp_path / "external",
        '{"source_url":"https://www.war.gov/medialink/ufo/release_1/'
        '059uap00011.pdf","page_num":1,"image_tags":["A metallic disc."]}\n',
    )

    mod = _load_script_module()
    rc = mod.build(
        ocr_dir=ocr_dir,
        manifest_path=tmp_path / "manifests" / "latest.json",
        out_path=out_path,
        embeddings_root=tmp_path / "embeddings",
        embed_model="voyage-3",
        augment_corpus=corpus,
        augment_miss_rate_threshold=0.5,
    )
    assert rc == 0
    docs = sorted(json.loads(out_path.read_text()), key=lambda d: d["page"])
    assert AUGMENT_BLOCK_HEADER in docs[0]["text"]
    assert AUGMENT_BLOCK_HEADER not in docs[1]["text"]


def test_augmented_run_requires_corpus_path_when_index_says_so(
    tmp_path: Path,
) -> None:
    """If the embed ``index.json`` declares augmentation but the operator
    didn't pass an ``--augment-from`` corpus to the build script, fail
    loudly. Producing a half-augmented payload (vectors say one thing,
    text says another) is exactly the bug vaivora flagged.
    """
    ocr_dir = tmp_path / "ocr"
    out_path = tmp_path / "pages.json"
    _stage_card(ocr_dir, "ff30c985595153f3", [(1, "page one")])
    _stage_manifest(
        tmp_path / "manifests",
        [
            {
                "card_id": "ff30c985595153f3",
                "title": "T",
                "asset_url": (
                    "https://www.war.gov/medialink/ufo/release_1/"
                    "059uap00011.pdf"
                ),
            }
        ],
    )
    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "rev",
        "sha256": "x" * 64,
    }
    _stage_index(tmp_path / "embeddings", "voyage-3", augmented_by)

    mod = _load_script_module()
    with pytest.raises(RuntimeError, match="augment"):
        mod.build(
            ocr_dir=ocr_dir,
            manifest_path=tmp_path / "manifests" / "latest.json",
            out_path=out_path,
            embeddings_root=tmp_path / "embeddings",
            embed_model="voyage-3",
            augment_corpus=None,
        )
