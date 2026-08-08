"""Tests for the embed pipeline orchestration.

The embedder is a fake (deterministic from the input text) so these tests
run without any network or API key. The shape under test is the on-disk
format the chat backend will read: ``vectors.bin`` (float32 [N, D]) plus
``index.json`` (per-row mapping + offsets).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from pursue_index.embed import pipeline as embed_pipeline
from pursue_index.embed.voyage import EmbedResult


class FakeEmbedder:
    """Deterministic 4-dim embedder. Returns hash-derived float32 vectors."""

    model = "voyage-3"
    usd_per_million_tokens = 0.06

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.dim = 4

    def embed_texts(self, texts: list[str], input_type: str = "document") -> EmbedResult:
        self.calls.append(list(texts))
        vectors: list[list[float]] = []
        for t in texts:
            seed = sum(ord(c) for c in t) or 1
            vectors.append([float(seed % (i + 7)) / 10.0 for i in range(self.dim)])
        return EmbedResult(vectors=vectors, total_tokens=sum(len(t) for t in texts))


def _write_card_pages(
    ocr_dir: Path, card_id: str, pages: list[str], status: str = "ok"
) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": status}))
    with (card_dir / "pages.jsonl").open("w") as fh:
        for i, text in enumerate(pages, start=1):
            fh.write(json.dumps({"page": i, "text": text, "confidence": 90.0}) + "\n")


def test_embed_run_writes_vectors_bin_and_index_json(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["alpha text", "beta text"])
    _write_card_pages(ocr_dir, "card_bbb", ["gamma text"])

    embedder = FakeEmbedder()
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir,
        out_root=out_root,
        embedder=embedder,
        batch_size=8,
    )

    out_dir = out_root / "voyage-3"
    vectors_path = out_dir / "vectors.bin"
    index_path = out_dir / "index.json"
    assert vectors_path.exists()
    assert index_path.exists()

    index = json.loads(index_path.read_text())
    assert index["model_id"] == "voyage-3"
    assert index["dim"] == 4
    assert index["n"] == 3
    rows = index["pages"]
    assert sorted((r["card_id"], r["page"]) for r in rows) == [
        ("card_aaa", 1),
        ("card_aaa", 2),
        ("card_bbb", 1),
    ]
    # offsets monotonically increase by dim*4 bytes (float32)
    sorted_rows = sorted(rows, key=lambda r: r["offset"])
    assert sorted_rows[0]["offset"] == 0
    assert sorted_rows[1]["offset"] == 4 * 4
    assert sorted_rows[2]["offset"] == 8 * 4

    # vectors.bin shape: 3 rows × 4 dims × 4 bytes
    raw = vectors_path.read_bytes()
    assert len(raw) == 3 * 4 * 4
    # Each row decodes to 4 little-endian float32s
    floats = struct.unpack("<12f", raw)
    assert all(isinstance(f, float) for f in floats)

    assert summary.embedded == 3
    assert summary.skipped == 0


def test_embed_run_skips_failed_ocr_cards(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_ok", ["good text"])
    _write_card_pages(ocr_dir, "card_bad", ["bad text"], status="failed")

    embedder = FakeEmbedder()
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=embedder, batch_size=8
    )

    assert summary.embedded == 1
    index = json.loads((out_root / "voyage-3" / "index.json").read_text())
    assert all(r["card_id"] == "card_ok" for r in index["pages"])


def test_embed_run_skips_empty_pages(tmp_path: Path) -> None:
    """Voyage rejects empty input strings with HTTP 400. Pages with no
    OCR text (near-blank scans where the LLM returned ``""`` or whitespace
    only) must be filtered before reaching the embedder so the run doesn't
    abort the whole batch on one empty page."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(
        ocr_dir,
        "card_mixed",
        ["real content", "", "   \n  ", "more real content"],
    )

    embedder = FakeEmbedder()
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=embedder, batch_size=8
    )

    # Two empty/whitespace pages dropped before reaching the embedder.
    for batch in embedder.calls:
        for text in batch:
            assert text.strip(), f"empty text reached embedder: {text!r}"

    assert summary.embedded == 2
    index = json.loads((out_root / "voyage-3" / "index.json").read_text())
    pages = sorted(r["page"] for r in index["pages"])
    assert pages == [1, 4]  # only the non-empty pages


def test_embed_run_is_idempotent_on_unchanged_corpus(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["alpha", "beta"])
    _write_card_pages(ocr_dir, "card_bbb", ["gamma"])

    first = FakeEmbedder()
    embed_pipeline.embed_run(ocr_dir=ocr_dir, out_root=out_root, embedder=first)
    bytes_after_first = (out_root / "voyage-3" / "vectors.bin").read_bytes()

    # Second run with a fresh embedder should make zero API calls.
    second = FakeEmbedder()
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=second
    )
    assert second.calls == []
    assert summary.embedded == 0
    assert summary.skipped == 3
    bytes_after_second = (out_root / "voyage-3" / "vectors.bin").read_bytes()
    assert bytes_after_first == bytes_after_second


def test_embed_run_only_embeds_changed_page(tmp_path: Path) -> None:
    """Editing one page's text should re-embed only that page."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["alpha", "beta"])

    first = FakeEmbedder()
    embed_pipeline.embed_run(ocr_dir=ocr_dir, out_root=out_root, embedder=first)

    # Rewrite page 2's text — text_sha changes, so it should re-embed.
    _write_card_pages(ocr_dir, "card_aaa", ["alpha", "beta CORRECTED"])

    second = FakeEmbedder()
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=second
    )
    # One new page sent to the embedder.
    assert sum(len(b) for b in second.calls) == 1
    assert summary.embedded == 1


def test_embed_run_offsets_let_caller_slice_vectors_bin(tmp_path: Path) -> None:
    """Roundtrip: read the binary back at each row's offset, get its vector."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["alpha", "beta"])

    embedder = FakeEmbedder()
    embed_pipeline.embed_run(ocr_dir=ocr_dir, out_root=out_root, embedder=embedder)

    out_dir = out_root / "voyage-3"
    raw = (out_dir / "vectors.bin").read_bytes()
    index = json.loads((out_dir / "index.json").read_text())
    dim = index["dim"]
    assert dim == 4
    assert len(raw) == index["n"] * dim * 4

    # Read each vector via its offset; verify length + dtype unpack works.
    for row in index["pages"]:
        chunk = raw[row["offset"] : row["offset"] + dim * 4]
        floats = struct.unpack(f"<{dim}f", chunk)
        assert len(floats) == dim


def test_embed_run_aborts_when_cost_exceeds_cap(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    # 4 million chars ≈ 1M tokens ≈ $0.06 — way under the $1 default. Force
    # the abort path with a tiny cap and a non-trivial corpus.
    _write_card_pages(ocr_dir, "card_aaa", ["alpha alpha alpha"] * 3)

    embedder = FakeEmbedder()
    with pytest.raises(RuntimeError, match="cap"):
        embed_pipeline.embed_run(
            ocr_dir=ocr_dir,
            out_root=out_root,
            embedder=embedder,
            cost_cap_usd=0.0,  # cap below any real cost → must abort
        )
    # No vectors written.
    assert not (out_root / "voyage-3" / "vectors.bin").exists()


def test_embed_run_uses_adapter_price_when_no_override(tmp_path: Path) -> None:
    """The pipeline reads ``embedder.usd_per_million_tokens`` so each adapter
    is the source of truth for its own rate. A 5×-priced adapter should
    trip a cap that the default Voyage rate would clear.
    """
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    # Big enough corpus to exercise the math: at $0.06/Mtok this is a few
    # cents; at $0.30/Mtok (5× drift) it should breach a $0.10 cap.
    big_text = "a" * 4_000_000  # ~1M tokens at chars/4
    _write_card_pages(ocr_dir, "card_aaa", [big_text])

    class ExpensiveEmbedder:
        model = "voyage-3"
        usd_per_million_tokens = 0.30  # 5× the Voyage rate

        def embed_texts(self, texts: list[str], input_type: str = "document"):
            return EmbedResult(vectors=[[0.0] * 4 for _ in texts], total_tokens=0)

    with pytest.raises(RuntimeError, match="cap"):
        embed_pipeline.embed_run(
            ocr_dir=ocr_dir,
            out_root=out_root,
            embedder=ExpensiveEmbedder(),
            cost_cap_usd=0.10,
        )


def test_embed_run_respects_explicit_usd_override(tmp_path: Path) -> None:
    """An explicit ``usd_per_million_tokens`` overrides the adapter default.

    Use case: forcing a tighter or looser cap from the CLI without editing
    the adapter (e.g. early-day pricing experiments).
    """
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    big_text = "a" * 4_000_000
    _write_card_pages(ocr_dir, "card_aaa", [big_text])

    class CheapEmbedder:
        model = "voyage-3"
        usd_per_million_tokens = 0.06

        def embed_texts(self, texts: list[str], input_type: str = "document"):
            return EmbedResult(vectors=[[0.0] * 4 for _ in texts], total_tokens=0)

    # Adapter default would be under cap, but override forces it over.
    with pytest.raises(RuntimeError, match="cap"):
        embed_pipeline.embed_run(
            ocr_dir=ocr_dir,
            out_root=out_root,
            embedder=CheapEmbedder(),
            cost_cap_usd=0.10,
            usd_per_million_tokens=0.30,
        )


# ---------------------------------------------------------------------------
# One row per (card_id, page): a re-embedded page supersedes its prior row
# rather than accumulating alongside it, and an index that already carries
# accumulated duplicates collapses to the newest row on the next write.
# ---------------------------------------------------------------------------


def test_re_embedding_changed_page_text_leaves_one_row(tmp_path: Path) -> None:
    """Re-OCR changes a page's text, so the next run embeds it again. The
    index must carry the new row only — not the new row alongside the old."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    index_path = out_root / "voyage-3" / "index.json"

    _write_card_pages(ocr_dir, "card_aaa", ["original page text", "page two"])
    embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder()
    )
    before = json.loads(index_path.read_text())["pages"]
    old_sha = next(r["text_sha"] for r in before if r["page"] == 1)

    _write_card_pages(ocr_dir, "card_aaa", ["re-ocr'd page text", "page two"])
    summary = embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder()
    )

    assert summary.embedded == 1
    payload = json.loads(index_path.read_text())
    rows = payload["pages"]
    page1 = [r for r in rows if r["card_id"] == "card_aaa" and r["page"] == 1]
    assert len(page1) == 1
    assert page1[0]["text_sha"] != old_sha
    assert payload["n"] == len(rows) == 2


def test_persist_supersedes_prior_row_for_the_same_page(tmp_path: Path) -> None:
    """A new row for a (card_id, page) replaces the prior row; untouched
    pages keep theirs."""
    from pursue_index.embed.store import IndexRow, write_index

    out = tmp_path / "voyage-3"
    out.mkdir(parents=True)
    vectors = out / "vectors.bin"
    vectors.write_bytes(b"\x00" * 32)
    index = out / "index.json"
    write_index(index, "voyage-3", 4, [
        IndexRow(card_id="card_aaa", page=1, text_sha="sha_old", offset=0),
        IndexRow(card_id="card_aaa", page=2, text_sha="sha2", offset=16),
    ])
    new_row = IndexRow(
        card_id="card_aaa", page=1, text_sha="sha_new", offset=32
    )
    embed_pipeline._persist(
        vectors, index, "voyage-3", 4, b"\x00" * 16, [new_row]
    )
    rows = json.loads(index.read_text())["pages"]
    assert [(r["page"], r["text_sha"]) for r in rows] == [
        (2, "sha2"),
        (1, "sha_new"),
    ]


def test_persist_collapses_duplicates_already_in_the_index(
    tmp_path: Path,
) -> None:
    """An index that accumulated duplicates before this rule existed collapses
    to the newest row per page (latest by store order) on the next write."""
    from pursue_index.embed.store import IndexRow, write_index

    out = tmp_path / "voyage-3"
    out.mkdir(parents=True)
    vectors = out / "vectors.bin"
    vectors.write_bytes(b"\x00" * 48)
    index = out / "index.json"
    write_index(index, "voyage-3", 4, [
        IndexRow(card_id="card_aaa", page=1, text_sha="sha_v1", offset=0),
        IndexRow(card_id="card_aaa", page=1, text_sha="sha_v2", offset=16),
        IndexRow(card_id="card_bbb", page=1, text_sha="sha_b", offset=32),
    ])
    new_row = IndexRow(card_id="card_ccc", page=1, text_sha="sha_c", offset=48)
    embed_pipeline._persist(
        vectors, index, "voyage-3", 4, b"\x00" * 16, [new_row]
    )
    payload = json.loads(index.read_text())
    keys = [(r["card_id"], r["page"], r["text_sha"]) for r in payload["pages"]]
    assert keys == [
        ("card_aaa", 1, "sha_v2"),
        ("card_bbb", 1, "sha_b"),
        ("card_ccc", 1, "sha_c"),
    ]
    assert payload["n"] == 3


def test_persist_does_not_resurrect_retired_augmented_by(tmp_path: Path) -> None:
    """After the alex-zhang42 augment retirement (2026-07-12), a subsequent run
    that doesn't re-pass ``augmented_by`` must NOT inherit the prior index's
    stale provenance block — it writes none, so the retired dataset can't
    silently persist across runs."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["page one"])

    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "abc123",
        "sha256": "deadbeef",
    }
    embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder(),
        augmented_by=augmented_by,
    )
    index = json.loads((out_root / "voyage-3" / "index.json").read_text())
    assert index.get("augmented_by") == augmented_by

    _write_card_pages(ocr_dir, "card_bbb", ["fresh content"])
    embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder()
    )
    index = json.loads((out_root / "voyage-3" / "index.json").read_text())
    assert "augmented_by" not in index


def test_persist_overrides_augmented_by_when_explicitly_passed(tmp_path: Path) -> None:
    """An explicit ``augmented_by`` on a later run replaces the prior block."""
    ocr_dir = tmp_path / "ocr"
    out_root = tmp_path / "embeddings"
    _write_card_pages(ocr_dir, "card_aaa", ["page one"])

    v1 = {"dataset": "alex-zhang42/ufo-pursue-open-atlas",
          "revision": "v1", "sha256": "11" * 32}
    embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder(),
        augmented_by=v1,
    )
    _write_card_pages(ocr_dir, "card_bbb", ["other content"])
    v2 = {"dataset": "alex-zhang42/ufo-pursue-open-atlas",
          "revision": "v2", "sha256": "22" * 32}
    embed_pipeline.embed_run(
        ocr_dir=ocr_dir, out_root=out_root, embedder=FakeEmbedder(),
        augmented_by=v2,
    )
    index = json.loads((out_root / "voyage-3" / "index.json").read_text())
    assert index.get("augmented_by") == v2
