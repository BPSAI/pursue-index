"""Tests for image-only page injection in the embed store + pipeline.

The external alex-zhang42 augment corpus was retired 2026-07-11. Genuinely
image-only pages (zero base OCR) now draw our own operator-reviewed vision-pass
text from the image-observations sidecars via ``obs_lookup``: an empty-OCR page
whose ``(card_id, page)`` is in the lookup embeds that text instead of being
dropped. Pages with real OCR are untouched.

The ``augmented``/``augmented_by`` on-disk fields are retained as vestigial
format support (to read indexes written before the retirement); the last two
tests pin that back-compat.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.store import (
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


def test_empty_page_dropped_without_obs_lookup(tmp_path: Path) -> None:
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, ""), (2, "real ocr text")])
    rows = _read_card_pages("card_aaa", pages_path)
    assert [r.page for r in rows] == [2]


def test_obs_lookup_fills_empty_page(tmp_path: Path) -> None:
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, "  ")])
    obs = {("card_aaa", 1): "[[IMAGE-OBSERVATIONS ...]] A photograph of a disc."}
    rows = _read_card_pages("card_aaa", pages_path, obs_lookup=obs)
    assert len(rows) == 1
    assert rows[0].text == obs[("card_aaa", 1)]
    assert rows[0].text_sha == text_sha(obs[("card_aaa", 1)])


def test_obs_lookup_ignored_for_pages_with_real_ocr(tmp_path: Path) -> None:
    """A page that already has OCR keeps it — obs text never overrides."""
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, "real ocr text")])
    obs = {("card_aaa", 1): "vision text that must NOT be used"}
    rows = _read_card_pages("card_aaa", pages_path, obs_lookup=obs)
    assert rows[0].text == "real ocr text"


def test_obs_lookup_drops_empty_page_not_in_lookup(tmp_path: Path) -> None:
    pages_path = tmp_path / "card_aaa" / "pages.jsonl"
    _write_pages(pages_path, [(1, ""), (2, "")])
    obs = {("card_aaa", 1): "only page 1 has vision text"}
    rows = _read_card_pages("card_aaa", pages_path, obs_lookup=obs)
    assert [r.page for r in rows] == [1]


def test_iter_card_pages_threads_obs_lookup_through(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    card_dir = ocr_dir / "card_xyz"
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    _write_pages(card_dir / "pages.jsonl", [(1, ""), (2, "page two")])
    obs = {("card_xyz", 1): "vision text for image-only page one"}
    rows = iter_card_pages(ocr_dir, obs_lookup=obs)
    assert {r.page for r in rows} == {1, 2}
    assert next(r for r in rows if r.page == 1).text == obs[("card_xyz", 1)]


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


def test_embed_run_embeds_image_only_page_from_obs_lookup(tmp_path: Path) -> None:
    """End-to-end: an empty-OCR page embeds via obs_lookup instead of dropping,
    and its text_sha matches the vision-pass text (not raw)."""
    from pursue_index.embed import pipeline as embed_pipeline

    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card(ocr_dir, "card_aaa", [(1, ""), (2, "ocr for page two")])
    obs = {("card_aaa", 1): "[[IMAGE-OBSERVATIONS ...]] A photograph of a disc."}

    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=_FakeEmbedder(),
        obs_lookup=obs,
    )
    assert summary.embedded == 2
    payload = json.loads((out_root / "voyage-3" / "index.json").read_text())
    p1 = next(p for p in payload["pages"] if p["page"] == 1)
    assert p1["text_sha"] == text_sha(obs[("card_aaa", 1)])
    # No new row is ever flagged augmented after the retirement.
    assert all("augmented" not in p for p in payload["pages"])


def test_write_index_records_augmented_by_provenance(tmp_path: Path) -> None:
    """Back-compat: ``augmented_by`` provenance is still writable/readable so a
    pre-retirement index round-trips."""
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
    index_path = tmp_path / "index.json"
    write_index(index_path, "voyage-3", 4, [])
    payload = json.loads(index_path.read_text())
    assert "augmented_by" not in payload
