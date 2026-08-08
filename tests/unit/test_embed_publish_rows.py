"""Tests for embed row selection: latest-wins dedupe + publish eligibility.

The embed store is append-only and keys "already embedded?" on
``(card_id, page, text_sha)``, so a re-OCR'd page mints a new row while the
old one stays. One row per ``(card_id, page)`` is the invariant every
consumer (index rewrite, published payload, atlas layout) needs; these tests
pin the shared helper that enforces it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pursue_index.embed.publish import (
    dedupe_latest_wins,
    load_embed_eligible_keys,
)


@dataclass
class _Row:
    card_id: str
    page: int
    tag: str


def _key(r: _Row) -> tuple[str, int]:
    return (r.card_id, r.page)


def test_dedupe_keeps_last_row_for_a_repeated_key() -> None:
    rows = [_Row("c1", 1, "old"), _Row("c1", 1, "new")]
    kept = dedupe_latest_wins(rows, _key)
    assert [r.tag for r in kept] == ["new"]


def test_dedupe_leaves_unique_keys_untouched() -> None:
    rows = [_Row("c1", 1, "a"), _Row("c1", 2, "b"), _Row("c2", 1, "c")]
    kept = dedupe_latest_wins(rows, _key)
    assert [r.tag for r in kept] == ["a", "b", "c"]


def test_dedupe_preserves_store_order_of_the_rows_it_keeps() -> None:
    """The kept row sits where the winning (last) occurrence sat, so callers
    that rely on ascending offset order stay ordered."""
    rows = [
        _Row("c1", 1, "old"),
        _Row("c2", 1, "only"),
        _Row("c1", 1, "new"),
        _Row("c3", 1, "tail"),
    ]
    kept = dedupe_latest_wins(rows, _key)
    assert [r.tag for r in kept] == ["only", "new", "tail"]


def test_dedupe_collapses_three_or_more_versions_of_one_page() -> None:
    rows = [_Row("c1", 1, "v1"), _Row("c1", 1, "v2"), _Row("c1", 1, "v3")]
    assert [r.tag for r in dedupe_latest_wins(rows, _key)] == ["v3"]


def _write_pages_json(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries))


def test_eligible_keys_are_pages_with_non_empty_text(tmp_path: Path) -> None:
    pages = tmp_path / "pages.json"
    _write_pages_json(pages, [
        {"card_id": "c1", "page": 1, "text": "readable ocr"},
        {"card_id": "c1", "page": 2, "text": ""},
        {"card_id": "c2", "page": 1, "text": "   "},
    ])
    assert load_embed_eligible_keys(pages) == {("c1", 1)}


def test_eligible_keys_tolerate_a_missing_text_field(tmp_path: Path) -> None:
    pages = tmp_path / "pages.json"
    _write_pages_json(pages, [
        {"card_id": "c1", "page": 1},
        {"card_id": "c1", "page": 2, "text": None},
    ])
    assert load_embed_eligible_keys(pages) == set()
