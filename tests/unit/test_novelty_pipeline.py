"""End-to-end test for the novelty compute pipeline.

Wires together: a fake PURSUE embed index on disk + a fake reference
embed index on disk + a manifest of card_ids → produces the
``data/novelty/latest.json`` sidecar shape the build helper consumes.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path


def _f32_bytes(rows: list[list[float]]) -> bytes:
    flat = [v for row in rows for v in row]
    return struct.pack(f"<{len(flat)}f", *flat)


def _write_embed_dir(
    base: Path,
    rows: list[tuple[str, int]],
    vectors: list[list[float]],
    model: str = "voyage-3",
) -> Path:
    out = base / model
    out.mkdir(parents=True, exist_ok=True)
    (out / "vectors.bin").write_bytes(_f32_bytes(vectors))
    dim = len(vectors[0]) if vectors else 0
    pages = [
        {"card_id": cid, "page": p, "text_sha": f"sha-{i}", "offset": i * dim * 4}
        for i, (cid, p) in enumerate(rows)
    ]
    (out / "index.json").write_text(
        json.dumps(
            {"model_id": model, "dim": dim, "n": len(vectors), "pages": pages}
        )
    )
    return out


def test_compute_novelty_writes_sidecar_with_disclosure_statuses(tmp_path: Path):
    from pursue_index.novelty.pipeline import compute_novelty

    pursue_dir = _write_embed_dir(
        tmp_path / "pursue",
        rows=[("card-A", 1), ("card-A", 2), ("card-B", 1)],
        # card-A pages match the reference; card-B does not.
        vectors=[
            [1.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
    )
    ref_dir = _write_embed_dir(
        tmp_path / "ref",
        rows=[("ref-001", 1), ("ref-002", 1)],
        vectors=[
            [1.0, 0.0, 0.0, 0.0],  # collinear with card-A pages
            [0.0, 1.0, 0.0, 0.0],
        ],
    )

    out = tmp_path / "novelty.json"
    report = compute_novelty(
        pursue_embed_dir=pursue_dir,
        reference_embed_dir=ref_dir,
        archive_id="synthetic",
        out_path=out,
    )

    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["archive_id"] == "synthetic"
    assert payload["thresholds"]["high"] == 0.85
    cards_by_id = {c["card_id"]: c for c in payload["cards"]}
    assert cards_by_id["card-A"]["disclosure_status"] == "previously-disclosed"
    assert cards_by_id["card-B"]["disclosure_status"] == "novel"
    assert report.cards_processed == 2


def test_compute_novelty_handles_empty_reference(tmp_path: Path):
    """Empty reference index → every card is trivially novel."""
    from pursue_index.novelty.pipeline import compute_novelty

    pursue_dir = _write_embed_dir(
        tmp_path / "pursue",
        rows=[("card-X", 1)],
        vectors=[[1.0, 0.0, 0.0, 0.0]],
    )
    ref_dir = tmp_path / "ref" / "voyage-3"
    ref_dir.mkdir(parents=True)
    (ref_dir / "vectors.bin").write_bytes(b"")
    (ref_dir / "index.json").write_text(
        '{"model_id": "voyage-3", "dim": 4, "n": 0, "pages": []}'
    )

    out = tmp_path / "novelty.json"
    compute_novelty(
        pursue_embed_dir=pursue_dir,
        reference_embed_dir=ref_dir,
        archive_id="empty",
        out_path=out,
    )
    payload = json.loads(out.read_text())
    assert payload["cards"][0]["disclosure_status"] == "novel"
