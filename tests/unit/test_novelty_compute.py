"""Tests for the novelty compute primitives.

Covers the cosine top-1 search and the cross-corpus comparison loop.
The reference embeddings are tiny in-memory float32 arrays — no Voyage
calls, no disk fixtures. The shape under test is the per-page match
record (best_match_card_id, best_match_page, similarity_score, archive_id).
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from pursue_index.novelty.compare import (
    PageMatch,
    ReferenceIndex,
    cosine_top1,
    load_reference_index,
)


def _f32_bytes(rows: list[list[float]]) -> bytes:
    flat = [v for row in rows for v in row]
    return struct.pack(f"<{len(flat)}f", *flat)


def test_cosine_top1_picks_highest_similarity():
    """Among three candidates, the colinear one wins outright."""
    query = [1.0, 0.0, 0.0]
    refs = [
        [0.0, 1.0, 0.0],  # orthogonal — sim 0
        [1.0, 0.0, 0.0],  # identical — sim 1
        [0.7, 0.7, 0.0],  # 45° — sim ~0.707
    ]
    idx, score = cosine_top1(query, refs)
    assert idx == 1
    assert score == pytest.approx(1.0, abs=1e-5)


def test_cosine_top1_returns_minus_one_on_empty_reference():
    """No references means no match — sentinel index, zero score."""
    idx, score = cosine_top1([1.0, 0.0, 0.0], [])
    assert idx == -1
    assert score == 0.0


def test_cosine_top1_handles_zero_vector_gracefully():
    """A zero query vector cannot match anything — sim is 0, not NaN."""
    refs = [[1.0, 0.0, 0.0]]
    idx, score = cosine_top1([0.0, 0.0, 0.0], refs)
    assert idx == 0
    assert score == 0.0


def test_load_reference_index_parses_disk_layout(tmp_path: Path):
    """``load_reference_index`` reads the same shape the embed pipeline writes."""
    ref_dir = tmp_path / "voyage-3"
    ref_dir.mkdir()
    vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    (ref_dir / "vectors.bin").write_bytes(_f32_bytes(vectors))
    (ref_dir / "index.json").write_text(
        '{"model_id": "voyage-3", "dim": 4, "n": 2, "pages": ['
        '{"card_id": "ref-001", "page": 1, "text_sha": "aaa", "offset": 0},'
        '{"card_id": "ref-002", "page": 5, "text_sha": "bbb", "offset": 16}]}'
    )

    ref = load_reference_index(ref_dir, archive_id="synthetic")
    assert isinstance(ref, ReferenceIndex)
    assert ref.archive_id == "synthetic"
    assert ref.dim == 4
    assert len(ref.vectors) == 2
    assert ref.rows[0].card_id == "ref-001"
    assert ref.rows[1].page == 5


def test_page_match_dataclass_round_trips():
    """PageMatch is a plain dataclass — verify the fields."""
    m = PageMatch(
        page=3,
        ref_card_id="ref-001",
        ref_page=2,
        similarity=0.91,
        archive_id="blackvault",
    )
    assert m.page == 3
    assert m.similarity == 0.91
    assert m.archive_id == "blackvault"
