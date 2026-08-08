"""Test the web-public embed build helper.

The script reads ``{data_root}/embeddings/{model_id}/`` and produces a
float16-packed binary plus a compact index for in-browser cosine
retrieval. We exercise it on a tiny fixture to verify the shape.
"""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_embed_data.py"


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_embed_data", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_embeddings(out_dir: Path, vectors: list[list[float]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    flat: list[float] = []
    for v in vectors:
        flat.extend(v)
    (out_dir / "vectors.bin").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    dim = len(vectors[0])
    (out_dir / "index.json").write_text(
        json.dumps(
            {
                "model_id": "voyage-3",
                "dim": dim,
                "n": len(vectors),
                "created_at": "2026-05-08T00:00:00Z",
                "pages": [
                    {
                        "card_id": f"card_{i // 2:03d}",
                        "page": (i % 2) + 1,
                        "text_sha": "x" * 64,
                        "offset": i * dim * 4,
                    }
                    for i in range(len(vectors))
                ],
            }
        )
    )


def _write_pages_json(
    out_dir: Path,
    keys: list[tuple[str, int]],
    *,
    empty_text: set[tuple[str, int]] | None = None,
) -> None:
    """Stage the ``pages.json`` the publish gate reads.

    Only pages with non-empty text are embed-eligible, so tests declare the
    key set they expect to survive (and, via ``empty_text``, the ones that
    exist but carry no readable OCR).
    """
    blank = empty_text or set()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pages.json").write_text(
        json.dumps([
            {
                "card_id": card_id,
                "page": page,
                "title": f"{card_id} page {page}",
                "text": "" if (card_id, page) in blank else "readable ocr",
            }
            for card_id, page in keys
        ])
    )


def _mirror_pages_json(in_dir: Path, out_dir: Path) -> None:
    """Declare every row in the staged embed index eligible."""
    index = json.loads((in_dir / "index.json").read_text())
    keys = [(r["card_id"], int(r["page"])) for r in index["pages"]]
    _write_pages_json(out_dir, sorted(set(keys)))


def test_build_embed_data_writes_float16_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    embeddings_root = tmp_path / "embeddings"
    web_root = tmp_path / "web"
    _write_embeddings(
        embeddings_root / "voyage-3",
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
            [0.9, 1.0, -0.1, -0.2],
        ],
    )
    _mirror_pages_json(
        embeddings_root / "voyage-3", web_root / "public" / "data"
    )

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root,
        model_id="voyage-3",
        out_dir=web_root / "public" / "data",
    )

    assert rc == 0
    bin_path = web_root / "public" / "data" / "embeddings.bin"
    idx_path = web_root / "public" / "data" / "embed_index.json"
    assert bin_path.exists()
    assert idx_path.exists()

    # 3 rows × 4 dims × 2 bytes (float16)
    assert bin_path.stat().st_size == 3 * 4 * 2

    idx = json.loads(idx_path.read_text())
    assert idx["model_id"] == "voyage-3"
    assert idx["dim"] == 4
    assert idx["n"] == 3
    # Compact: pages is a list-of-lists [[card_id, page]], not dicts
    assert idx["pages"] == [
        ["card_000", 1],
        ["card_000", 2],
        ["card_001", 1],
    ]


def test_build_embed_data_logs_size_warning_when_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Output >10 MB should raise a visible warning so we know to revisit."""
    embeddings_root = tmp_path / "embeddings"
    web_root = tmp_path / "web"
    # Write 6 vectors of 1024 dims each = 6 * 1024 * 2 = 12 KB. We force the
    # warning path by passing a very low threshold.
    _write_embeddings(
        embeddings_root / "voyage-3",
        [[0.1] * 1024 for _ in range(6)],
    )
    _mirror_pages_json(
        embeddings_root / "voyage-3", web_root / "public" / "data"
    )

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root,
        model_id="voyage-3",
        out_dir=web_root / "public" / "data",
        warn_threshold_bytes=1024,
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert "warn" in captured.lower() or "WARNING" in captured


def _write_embeddings_with_augmentation(
    out_dir: Path,
    rows: list[dict],
    vectors: list[list[float]],
    augmented_by: dict[str, str] | None = None,
) -> None:
    """Helper: write a synthetic embed root with explicit page rows.

    Lets a test stage two rows for the same ``(card_id, page)`` (one
    augmented, one un-augmented) to exercise vaivora's orphan-drop
    finding.
    """
    import struct as _struct

    out_dir.mkdir(parents=True, exist_ok=True)
    flat: list[float] = []
    for v in vectors:
        flat.extend(v)
    (out_dir / "vectors.bin").write_bytes(
        _struct.pack(f"<{len(flat)}f", *flat)
    )
    payload: dict = {
        "model_id": "voyage-3",
        "dim": len(vectors[0]),
        "n": len(vectors),
        "created_at": "2026-05-08T00:00:00Z",
        "pages": rows,
    }
    if augmented_by is not None:
        payload["augmented_by"] = augmented_by
    (out_dir / "index.json").write_text(json.dumps(payload))


def test_build_embed_data_drops_augmented_by(
    tmp_path: Path,
) -> None:
    """After the alex-zhang42 augment retirement (2026-07-12), the deployed
    ``embed_index.json`` carries NO ``augmented_by`` block even if a legacy
    source ``index.json`` still has one — the build no longer propagates it,
    so a stale retired-dataset provenance can't leak into the web payload.
    """
    embeddings_root = tmp_path / "embeddings"
    web_root = tmp_path / "web"
    rows = [
        {"card_id": "c0", "page": 1, "text_sha": "a" * 64, "offset": 0},
        {"card_id": "c1", "page": 1, "text_sha": "b" * 64, "offset": 16},
    ]
    augmented_by = {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "b0f0c79924b88d339846aa9fc4283958fe15682b",
        "sha256": "c" * 64,
    }
    _write_embeddings_with_augmentation(
        embeddings_root / "voyage-3",
        rows,
        [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
        augmented_by=augmented_by,
    )
    _mirror_pages_json(
        embeddings_root / "voyage-3", web_root / "public" / "data"
    )

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root,
        model_id="voyage-3",
        out_dir=web_root / "public" / "data",
    )
    assert rc == 0
    idx = json.loads(
        (web_root / "public" / "data" / "embed_index.json").read_text()
    )
    assert "augmented_by" not in idx


def test_build_embed_data_omits_augmented_by_when_source_lacks_it(
    tmp_path: Path,
) -> None:
    """A non-augmented source index must not invent an ``augmented_by``."""
    embeddings_root = tmp_path / "embeddings"
    web_root = tmp_path / "web"
    _write_embeddings(
        embeddings_root / "voyage-3",
        [[0.1, 0.2, 0.3, 0.4]],
    )
    _mirror_pages_json(
        embeddings_root / "voyage-3", web_root / "public" / "data"
    )
    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root,
        model_id="voyage-3",
        out_dir=web_root / "public" / "data",
    )
    assert rc == 0
    idx = json.loads(
        (web_root / "public" / "data" / "embed_index.json").read_text()
    )
    assert "augmented_by" not in idx


def _stage_superseded_page_fixture(embeddings_root: Path) -> None:
    """Two rows for ``(c0, 1)`` — a re-OCR'd page's prior and current row —
    plus one untouched ``(c1, 2)`` row. Store order (ascending offset) makes
    the second ``(c0, 1)`` row the current one.
    """
    rows = [
        {"card_id": "c0", "page": 1, "text_sha": "a" * 64, "offset": 0},
        {"card_id": "c0", "page": 1, "text_sha": "b" * 64, "offset": 16},
        {"card_id": "c1", "page": 2, "text_sha": "c" * 64, "offset": 32},
    ]
    _write_embeddings_with_augmentation(
        embeddings_root / "voyage-3",
        rows,
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.9, 1.0, 1.1, 1.2],
            [0.5, 0.6, 0.7, 0.8],
        ],
    )


def test_build_embed_data_publishes_one_row_per_page(tmp_path: Path) -> None:
    """When two rows share ``(card_id, page)``, publish the later one only.

    The embed store appends a fresh row when a page is re-OCR'd, so both the
    superseded and the current row sit in ``index.json``. Shipping both wastes
    top-k slots and lets retrieval cite a stale page-version.
    """
    import numpy as np

    embeddings_root = tmp_path / "embeddings"
    out_dir = tmp_path / "web" / "public" / "data"
    _stage_superseded_page_fixture(embeddings_root)
    _write_pages_json(out_dir, [("c0", 1), ("c1", 2)])

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root, model_id="voyage-3", out_dir=out_dir
    )
    assert rc == 0
    idx = json.loads((out_dir / "embed_index.json").read_text())
    assert idx["n"] == 2
    assert idx["pages"] == [["c0", 1], ["c1", 2]]
    # The binary file must shrink in lockstep — 2 rows × 4 dims × 2 bytes.
    bin_path = out_dir / "embeddings.bin"
    assert bin_path.stat().st_size == 2 * 4 * 2
    # The kept (c0, 1) vector must be the later one (0.9, 1.0, 1.1, 1.2),
    # not the superseded prior (0.1, 0.2, 0.3, 0.4).
    arr = np.frombuffer(bin_path.read_bytes(), dtype="<f2").reshape(2, 4)
    assert pytest.approx(float(arr[0, 0]), abs=1e-2) == 0.9


def test_build_embed_data_excludes_pages_with_empty_text(tmp_path: Path) -> None:
    """A page whose ``pages.json`` entry carries no text is embed-ineligible:
    retrieval has nothing to build a snippet from."""
    embeddings_root = tmp_path / "embeddings"
    out_dir = tmp_path / "web" / "public" / "data"
    _write_embeddings(
        embeddings_root / "voyage-3",
        [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
    )
    _write_pages_json(
        out_dir,
        [("card_000", 1), ("card_000", 2)],
        empty_text={("card_000", 2)},
    )

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root, model_id="voyage-3", out_dir=out_dir
    )
    assert rc == 0
    idx = json.loads((out_dir / "embed_index.json").read_text())
    assert idx["pages"] == [["card_000", 1]]
    assert (out_dir / "embeddings.bin").stat().st_size == 1 * 4 * 2


def test_build_embed_data_excludes_rows_absent_from_pages_json(
    tmp_path: Path,
) -> None:
    """A card that left the corpus keeps its rows in the append-only store;
    those rows must not reach the published index."""
    embeddings_root = tmp_path / "embeddings"
    out_dir = tmp_path / "web" / "public" / "data"
    _write_embeddings(
        embeddings_root / "voyage-3",
        [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]],
    )
    _write_pages_json(out_dir, [("card_000", 1)])

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root, model_id="voyage-3", out_dir=out_dir
    )
    assert rc == 0
    idx = json.loads((out_dir / "embed_index.json").read_text())
    assert idx["pages"] == [["card_000", 1]]


def test_build_embed_data_fails_when_pages_json_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``pages.json`` the eligibility gate cannot run, so the build
    stops rather than publishing an ungated index."""
    embeddings_root = tmp_path / "embeddings"
    out_dir = tmp_path / "web" / "public" / "data"
    _write_embeddings(embeddings_root / "voyage-3", [[0.1, 0.2, 0.3, 0.4]])

    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embeddings_root, model_id="voyage-3", out_dir=out_dir
    )
    assert rc == 1
    assert "pages.json" in capsys.readouterr().err
    assert not (out_dir / "embed_index.json").exists()
