"""Tests for the alex-zhang42 augmentation injection in the embed store.

The store's ``_read_card_pages`` reads OCR pages.jsonl and emits PageRow
objects. When the optional ``augment_lookup`` argument is set, each page
that has matching ``[image_tags...]`` should append a deterministic
``[[IMAGE-DESCRIPTIONS via ...]]`` block to its text BEFORE the
``text_sha`` is computed — so the augmented row gets a different hash
and the existing idempotency layer treats it as new.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.store import (
    AUGMENT_BLOCK_HEADER,
    IndexRow,
    _read_card_pages,
    iter_card_pages,
    text_sha,
    write_index,
)


def _write_pages(path: Path, pages: list[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for page, text in pages:
            fh.write(json.dumps({"page": page, "text": text}) + "\n")


def test_augment_lookup_appends_image_descriptions_block(tmp_path: Path) -> None:
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, "OCR text for page one.")])

    augment = {
        ("card_aaa", 1): [
            "A photograph of a metallic disc.",
            "Margin note marked CONFIDENTIAL.",
        ]
    }
    rows = _read_card_pages("card_aaa", pages_path, augment_lookup=augment)
    assert len(rows) == 1
    text = rows[0].text
    assert "OCR text for page one." in text
    assert AUGMENT_BLOCK_HEADER in text
    assert "- A photograph of a metallic disc." in text
    assert "- Margin note marked CONFIDENTIAL." in text


def test_augment_lookup_changes_text_sha_versus_unaugmented(tmp_path: Path) -> None:
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, "OCR text for page one.")])

    base = _read_card_pages("card_aaa", pages_path)
    augment = {("card_aaa", 1): ["A photograph of a metallic disc."]}
    aug = _read_card_pages("card_aaa", pages_path, augment_lookup=augment)

    assert base[0].text_sha != aug[0].text_sha
    # The base sha should still match the un-augmented OCR text directly.
    assert base[0].text_sha == text_sha("OCR text for page one.")


def test_augment_lookup_skips_pages_without_matching_tags(tmp_path: Path) -> None:
    """Pages whose ``(card_id, page)`` is not in the augment_lookup must
    be left untouched — they're the un-augmented baseline.
    """
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, "first"), (2, "second")])
    augment = {("card_aaa", 2): ["only page 2 has a tag"]}

    rows = _read_card_pages("card_aaa", pages_path, augment_lookup=augment)
    page_1 = next(r for r in rows if r.page == 1)
    page_2 = next(r for r in rows if r.page == 2)
    assert AUGMENT_BLOCK_HEADER not in page_1.text
    assert AUGMENT_BLOCK_HEADER in page_2.text


def test_write_index_records_augmented_by_provenance(tmp_path: Path) -> None:
    """When the pipeline ran with augmentation, ``index.json`` must carry
    a structured ``augmented_by`` block so a reader of the deployed
    payload can tell exactly which dataset + revision shaped the text.
    Forensic provenance — non-negotiable per the plan.
    """
    index_path = tmp_path / "index.json"
    rows = [IndexRow(card_id="c1", page=1, text_sha="abc", offset=0)]
    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "b0f0c79924b88d339846aa9fc4283958fe15682b",
        "sha256": "deadbeef",
    }
    write_index(index_path, "voyage-3", 4, rows, augmented_by=augmented_by)
    payload = json.loads(index_path.read_text())
    assert payload["augmented_by"] == augmented_by


def test_write_index_omits_augmented_by_when_unaugmented(tmp_path: Path) -> None:
    """An un-augmented run must NOT set ``augmented_by`` (or set it to
    null) so the field's presence is itself a signal that augmentation
    happened. We omit the key entirely to keep the payload small.
    """
    index_path = tmp_path / "index.json"
    write_index(index_path, "voyage-3", 4, [])
    payload = json.loads(index_path.read_text())
    assert "augmented_by" not in payload


class _FakeEmbedder:
    """Minimal embedder used to drive embed_run end-to-end without Voyage."""

    model = "voyage-3"
    usd_per_million_tokens = 0.06

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str], input_type: str = "document"):
        from pursue_index.embed.voyage import EmbedResult

        self.calls.append(list(texts))
        return EmbedResult(
            vectors=[[0.0, 0.1, 0.2, 0.3] for _ in texts],
            total_tokens=sum(len(t) for t in texts),
        )


def _write_card(ocr_dir: Path, card_id: str, pages: list[tuple[int, str]]) -> None:
    card = ocr_dir / card_id
    card.mkdir(parents=True, exist_ok=True)
    (card / "meta.json").write_text(json.dumps({"status": "ok"}))
    with (card / "pages.jsonl").open("w") as fh:
        for page, text in pages:
            fh.write(json.dumps({"page": page, "text": text}) + "\n")


def test_embed_run_records_augmented_by_in_index(tmp_path: Path) -> None:
    """End-to-end: when embed_run is called with an ``augment_lookup`` AND
    ``augmented_by`` provenance, the resulting ``index.json`` carries the
    provenance block AND the augmented page's ``text_sha`` matches the
    sha of the augmented (not raw) text.
    """
    from pursue_index.embed import pipeline as embed_pipeline

    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card(ocr_dir, "card_aaa", [(1, "OCR text for page one.")])

    augment = {("card_aaa", 1): ["A photograph of a metallic disc."]}
    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "b0f0c79924b88d339846aa9fc4283958fe15682b",
        "sha256": "abc123",
    }
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir,
        out_root=out_root,
        embedder=_FakeEmbedder(),
        augment_lookup=augment,
        augmented_by=augmented_by,
    )
    assert summary.embedded == 1
    payload = json.loads((out_root / "voyage-3" / "index.json").read_text())
    assert payload["augmented_by"] == augmented_by
    # The augmented row's text_sha is sha256(OCR text + IMAGE-DESCRIPTIONS block).
    expected = text_sha(
        "OCR text for page one.\n\n"
        + AUGMENT_BLOCK_HEADER
        + "\n- A photograph of a metallic disc."
    )
    assert payload["pages"][0]["text_sha"] == expected


def test_iter_card_pages_threads_augment_lookup_through(tmp_path: Path) -> None:
    """``iter_card_pages`` must accept ``augment_lookup`` and pass it down
    to each call of ``_read_card_pages`` — that's the public seam the
    pipeline uses.
    """
    ocr_dir = tmp_path / "ocr"
    card_dir = ocr_dir / "card_xyz"
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    _write_pages(card_dir / "pages.jsonl", [(1, "page one"), (2, "page two")])

    augment = {("card_xyz", 1): ["a tag for page one"]}
    rows = iter_card_pages(ocr_dir, augment_lookup=augment)
    assert len(rows) == 2
    p1 = next(r for r in rows if r.page == 1)
    p2 = next(r for r in rows if r.page == 2)
    assert AUGMENT_BLOCK_HEADER in p1.text
    assert AUGMENT_BLOCK_HEADER not in p2.text
