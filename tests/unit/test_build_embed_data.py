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
