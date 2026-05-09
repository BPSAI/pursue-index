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


def test_build_embed_data_propagates_augmented_by(
    tmp_path: Path,
) -> None:
    """When the source ``index.json`` carries ``augmented_by``, the
    deployed ``embed_index.json`` must too (vaivora blocker #2).

    Provenance dies in transit if ``_write_index`` strips it; the worker
    and the cite.astro page rely on this block to identify augmented
    pages downstream.
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
    assert idx["augmented_by"] == augmented_by


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


def _stage_orphan_drift_fixture(embeddings_root: Path) -> None:
    """Two rows for ``(c0, 1)`` (un-augmented prior + augmented sibling)
    plus one untouched ``(c1, 2)`` row — exactly the shape vaivora's
    blocker #3 describes.
    """
    rows = [
        {"card_id": "c0", "page": 1, "text_sha": "a" * 64, "offset": 0,
         "augmented": False},
        {"card_id": "c0", "page": 1, "text_sha": "b" * 64, "offset": 16,
         "augmented": True},
        {"card_id": "c1", "page": 2, "text_sha": "c" * 64, "offset": 32,
         "augmented": False},
    ]
    _write_embeddings_with_augmentation(
        embeddings_root / "voyage-3",
        rows,
        [
            [0.1, 0.2, 0.3, 0.4],
            [0.9, 1.0, 1.1, 1.2],
            [0.5, 0.6, 0.7, 0.8],
        ],
        augmented_by={
            "dataset": "alex-zhang42/ufo-pursue-open-atlas",
            "revision": "rev",
            "sha256": "d" * 64,
        },
    )


def test_build_embed_data_drops_orphan_unaugmented_rows(
    tmp_path: Path,
) -> None:
    """When two rows share ``(card_id, page)``, keep only the augmented one.

    Per vaivora blocker #3: after an augmented run, both the prior
    un-augmented row and the new augmented row sit in ``index.json``.
    Shipping both would double the top-k slot count for those pages.
    """
    import numpy as np

    embeddings_root = tmp_path / "embeddings"
    web_root = tmp_path / "web"
    _stage_orphan_drift_fixture(embeddings_root)

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
    # Only 2 rows survive: the augmented (c0, 1) and the un-augmented (c1, 2).
    assert idx["n"] == 2
    assert idx["pages"] == [["c0", 1], ["c1", 2]]
    # The binary file must shrink in lockstep — 2 rows × 4 dims × 2 bytes.
    bin_path = web_root / "public" / "data" / "embeddings.bin"
    assert bin_path.stat().st_size == 2 * 4 * 2
    # The kept (c0, 1) vector must be the augmented one (0.9, 1.0, 1.1, 1.2),
    # not the un-augmented prior (0.1, 0.2, 0.3, 0.4).
    arr = np.frombuffer(bin_path.read_bytes(), dtype="<f2").reshape(2, 4)
    assert pytest.approx(float(arr[0, 0]), abs=1e-2) == 0.9
