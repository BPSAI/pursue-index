"""Tests for ``scripts/build_atlas_layout.py``.

The script reads the native embedding root (float32 ``vectors.bin`` +
``index.json``), runs UMAP for a 2D projection, joins agency from the
manifest by ``card_id``, and writes
``web/public/data/atlas-layout.json``. The shape is documented in
``.paircoder/plans/semantic-browser.md``.
"""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_atlas_layout.py"


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_atlas_layout", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_native_embeddings(
    out_dir: Path,
    vectors: list[list[float]],
    *,
    augmented_by: dict[str, str] | None = None,
) -> None:
    """Write a minimal native embed root (``vectors.bin`` + ``index.json``).

    Mirrors the on-disk shape produced by ``pursue embed run``. Tests
    construct synthetic vectors with deliberate cluster structure so we
    can assert UMAP output shape without depending on the real corpus.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    flat: list[float] = []
    for v in vectors:
        flat.extend(v)
    (out_dir / "vectors.bin").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    dim = len(vectors[0])
    payload: dict[str, object] = {
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
    if augmented_by is not None:
        payload["augmented_by"] = augmented_by
    (out_dir / "index.json").write_text(json.dumps(payload))


def _write_manifest(path: Path, agencies: dict[str, str]) -> None:
    """Write a minimal manifest mapping card_id → agency."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_url": "https://example/",
                "fetched_at": "2026-05-08T00:00:00Z",
                "csv_sha256": "0" * 64,
                "cards": [
                    {
                        "card_id": cid,
                        "title": f"card {cid}",
                        "asset_type": "PDF",
                        "agency": agency,
                        "release_date": None,
                        "redacted": False,
                    }
                    for cid, agency in agencies.items()
                ],
            }
        )
    )


def _seed_inputs(tmp_path: Path, *, n_cards: int = 6) -> tuple[Path, Path, Path]:
    """Common fixture: write embeddings + manifest, return key paths.

    Two pages per card, each card lands at a different cluster centre in
    a 4-dim space. Six cards × 2 pages = 12 vectors — enough for UMAP
    with ``n_neighbors=2`` (we pass a small ``n_neighbors`` from tests).
    """
    embed_root = tmp_path / "embeddings"
    centres = [
        [10.0, 0.0, 0.0, 0.0],
        [0.0, 10.0, 0.0, 0.0],
        [0.0, 0.0, 10.0, 0.0],
        [-10.0, 0.0, 0.0, 0.0],
        [0.0, -10.0, 0.0, 0.0],
        [0.0, 0.0, -10.0, 0.0],
    ][:n_cards]
    vectors: list[list[float]] = []
    for c in centres:
        # Two slightly-jittered pages per card.
        vectors.append([x + 0.01 for x in c])
        vectors.append([x - 0.01 for x in c])
    _write_native_embeddings(embed_root / "voyage-3", vectors)
    manifest = tmp_path / "manifests" / "latest.json"
    agencies = {
        f"card_{i:03d}": ["FBI", "Department of War", "NASA", "Department of State"][
            i % 4
        ]
        for i in range(n_cards)
    }
    _write_manifest(manifest, agencies)
    out_dir = tmp_path / "web" / "public" / "data"
    return embed_root, manifest, out_dir


def test_build_writes_atlas_layout_with_expected_shape(tmp_path: Path) -> None:
    embed_root, manifest, out_dir = _seed_inputs(tmp_path)
    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embed_root,
        model_id="voyage-3",
        manifest_path=manifest,
        out_dir=out_dir,
        n_neighbors=2,
        random_state=42,
    )
    assert rc == 0
    layout = json.loads((out_dir / "atlas-layout.json").read_text())
    assert layout["model_id"] == "voyage-3"
    assert layout["n"] == 12
    pts = layout["points"]
    assert len(pts) == 12
    sample = pts[0]
    for key in ("card_id", "page", "x", "y", "agency"):
        assert key in sample
    assert isinstance(sample["x"], float)
    assert isinstance(sample["y"], float)
    # Agency joined from manifest, not "UNKNOWN".
    assert sample["agency"] in {"FBI", "Department of War", "NASA", "Department of State"}


def test_build_is_deterministic_under_fixed_seed(tmp_path: Path) -> None:
    embed_root, manifest, out_dir = _seed_inputs(tmp_path)
    mod = _load_script_module()
    out_a = out_dir / "a"
    out_b = out_dir / "b"
    for out in (out_a, out_b):
        mod.build(
            embeddings_root=embed_root,
            model_id="voyage-3",
            manifest_path=manifest,
            out_dir=out,
            n_neighbors=2,
            random_state=42,
        )
    a = json.loads((out_a / "atlas-layout.json").read_text())["points"]
    b = json.loads((out_b / "atlas-layout.json").read_text())["points"]
    # Coordinate equality across runs given identical seed + inputs.
    for pa, pb in zip(a, b, strict=True):
        assert pa["card_id"] == pb["card_id"]
        assert pa["page"] == pb["page"]
        assert pa["x"] == pytest.approx(pb["x"], abs=1e-6)
        assert pa["y"] == pytest.approx(pb["y"], abs=1e-6)


def test_build_tolerates_orphan_vector_bytes(tmp_path: Path) -> None:
    """After an augmented embed run, ``vectors.bin`` may carry bytes for
    rows that ``index.json`` no longer references (the un-augmented
    sibling whose augmented twin won the dedupe). The atlas builder must
    follow the same offset-based addressing as ``build_embed_data.py``.
    """
    embed_root, manifest, out_dir = _seed_inputs(tmp_path)
    # Append two orphan vectors past the indexed range — vectors.bin grows
    # but index.json's pages list stays the same. Indexed rows should still
    # land at their original offsets.
    extra = struct.pack(f"<{4 * 2}f", 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0)
    bin_path = embed_root / "voyage-3" / "vectors.bin"
    bin_path.write_bytes(bin_path.read_bytes() + extra)
    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embed_root,
        model_id="voyage-3",
        manifest_path=manifest,
        out_dir=out_dir,
        n_neighbors=2,
        random_state=42,
    )
    assert rc == 0
    layout = json.loads((out_dir / "atlas-layout.json").read_text())
    assert layout["n"] == 12  # The 2 orphan vectors are not indexed.


def test_build_preserves_augmented_by_provenance(tmp_path: Path) -> None:
    embed_root = tmp_path / "embeddings"
    _write_native_embeddings(
        embed_root / "voyage-3",
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        augmented_by={
            "dataset": "alex-zhang42/ufo-pursue-open-atlas",
            "revision": "abc123",
            "sha256": "deadbeef",
        },
    )
    manifest = tmp_path / "manifests" / "latest.json"
    _write_manifest(manifest, {f"card_{i:03d}": "FBI" for i in range(2)})
    out_dir = tmp_path / "web" / "public" / "data"
    mod = _load_script_module()
    mod.build(
        embeddings_root=embed_root,
        model_id="voyage-3",
        manifest_path=manifest,
        out_dir=out_dir,
        n_neighbors=2,
        random_state=42,
    )
    layout = json.loads((out_dir / "atlas-layout.json").read_text())
    assert layout["augmented_by"]["dataset"] == "alex-zhang42/ufo-pursue-open-atlas"
    assert layout["augmented_by"]["sha256"] == "deadbeef"


def test_build_from_published_payload(tmp_path: Path) -> None:
    """The published float16 path is the CI-friendly fallback when the
    native embed root isn't available. Exercise it end-to-end on a
    synthetic published payload mirroring ``build_embed_data.py``'s
    output shape (compact ``[[card_id, page], ...]`` rows + float16).
    """
    web_data = tmp_path / "web" / "public" / "data"
    web_data.mkdir(parents=True)
    n, dim = 12, 4
    np_local = np.random.default_rng(0).standard_normal((n, dim)).astype(np.float16)
    (web_data / "embeddings.bin").write_bytes(np_local.tobytes(order="C"))
    pages = [[f"card_{i // 2:03d}", (i % 2) + 1] for i in range(n)]
    (web_data / "embed_index.json").write_text(
        json.dumps(
            {
                "model_id": "voyage-3",
                "dim": dim,
                "n": n,
                "pages": pages,
                "augmented_by": {"dataset": "x", "revision": "y", "sha256": "z"},
            }
        )
    )
    manifest = tmp_path / "manifests" / "latest.json"
    _write_manifest(manifest, {f"card_{i:03d}": "FBI" for i in range(n // 2)})
    out_dir = tmp_path / "out"
    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=tmp_path / "unused",
        model_id="voyage-3",
        manifest_path=manifest,
        out_dir=out_dir,
        n_neighbors=2,
        random_state=42,
        from_published=web_data,
    )
    assert rc == 0
    layout = json.loads((out_dir / "atlas-layout.json").read_text())
    assert layout["n"] == n
    assert layout["augmented_by"]["dataset"] == "x"
    # Every point keys back to a card_id we wrote into the manifest.
    for p in layout["points"]:
        assert p["agency"] == "FBI"


# Lazy import for the np usage in the test above.
import numpy as np  # noqa: E402


def test_write_layout_is_atomic_no_tmp_left_on_success(tmp_path: Path) -> None:
    """``_write_layout`` must write via ``.tmp`` + ``os.replace`` so a crash
    mid-write can't leave ``atlas-layout.json`` half-written. After a clean
    run, the ``.tmp`` sibling must NOT exist on disk — its presence would
    indicate the script wrote directly without the rename, or that a
    previous failed run wasn't cleaned up.
    """
    mod = _load_script_module()
    out_path = tmp_path / "atlas-layout.json"
    mod._write_layout(
        out_path,
        model_id="voyage-3",
        points=[{"card_id": "x", "page": 1, "x": 0.1, "y": 0.2, "agency": "FBI"}],
        augmented_by=None,
    )
    assert out_path.exists()
    # Atomic-write tmp sibling must be cleaned up after rename.
    siblings = [p.name for p in tmp_path.iterdir()]
    assert all(not name.endswith(".tmp") for name in siblings), (
        f"unexpected .tmp leftover in {siblings} — _write_layout did not "
        f"replace atomically"
    )


def test_write_layout_preserves_existing_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the atomic rename fails (filesystem hiccup, EACCES, etc.), the
    pre-existing ``atlas-layout.json`` must remain intact. Verifies the
    write-tmp-then-replace contract by patching ``os.replace`` to raise
    after the tmp file has been written.
    """
    import os as _os

    mod = _load_script_module()
    out_path = tmp_path / "atlas-layout.json"
    out_path.write_text('{"preserved": true}')

    def _boom(src: object, dst: object) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(_os, "replace", _boom)
    with pytest.raises(OSError, match="simulated rename failure"):
        mod._write_layout(
            out_path,
            model_id="voyage-3",
            points=[{"card_id": "x", "page": 1, "x": 0.1, "y": 0.2, "agency": "FBI"}],
            augmented_by=None,
        )
    # Original file untouched — the corrupted-half-write hazard is the
    # exact thing atomic write is designed to prevent.
    assert json.loads(out_path.read_text()) == {"preserved": True}


def test_normalize_coords_maps_into_unit_square() -> None:
    """Coordinates must be normalized into ``[-1, 1]`` so regl-scatterplot's
    default unit-square camera frames the cluster.

    Without this, UMAP output (typically ``x ∈ [-6, 19], y ∈ [-3, 21]``)
    ships off-camera and the deployed canvas renders empty.
    """
    mod = _load_script_module()
    coords = np.array(
        [
            [-6.17, -2.98],
            [19.28, 21.41],
            [5.64, 7.73],
        ],
        dtype=np.float32,
    )
    out = mod._normalize_coords(coords)
    assert out.shape == coords.shape
    assert float(out[:, 0].min()) >= -1.0 - 1e-6
    assert float(out[:, 0].max()) <= 1.0 + 1e-6
    assert float(out[:, 1].min()) >= -1.0 - 1e-6
    assert float(out[:, 1].max()) <= 1.0 + 1e-6


def test_normalize_coords_preserves_aspect_ratio() -> None:
    """Asymmetric shapes (different x and y spans) must keep their
    relative spans after scaling — UMAP's geometry must not be squashed
    along one axis.
    """
    mod = _load_script_module()
    coords = np.array(
        [
            [0.0, 0.0],
            [10.0, 0.0],
            [10.0, 5.0],
            [0.0, 5.0],
        ],
        dtype=np.float32,
    )
    out = mod._normalize_coords(coords)
    raw_aspect = (coords[:, 0].max() - coords[:, 0].min()) / (
        coords[:, 1].max() - coords[:, 1].min()
    )
    norm_aspect = (out[:, 0].max() - out[:, 0].min()) / (
        out[:, 1].max() - out[:, 1].min()
    )
    assert norm_aspect == pytest.approx(raw_aspect, abs=1e-5)
    # Wider axis (x) must span the full [-1, 1].
    assert float(out[:, 0].min()) == pytest.approx(-1.0, abs=1e-6)
    assert float(out[:, 0].max()) == pytest.approx(1.0, abs=1e-6)
    # Narrower axis (y) is centered around 0 with proportional scaling
    # — span = 5/10 = 0.5 of the wider axis = [-0.5, 0.5].
    assert float(out[:, 1].min()) == pytest.approx(-0.5, abs=1e-6)
    assert float(out[:, 1].max()) == pytest.approx(0.5, abs=1e-6)


def test_normalize_coords_known_point_maps_as_expected() -> None:
    """Spec a specific input/output pair so regressions in the centering
    formula surface as a single-line failure.
    """
    mod = _load_script_module()
    # x ∈ [-6, 18] → center 6, half_range 12.
    # y ∈ [-2, 22] → center 10, half_range 12 (same span).
    coords = np.array(
        [[-6.0, -2.0], [18.0, 22.0], [6.0, 10.0]],
        dtype=np.float32,
    )
    out = mod._normalize_coords(coords)
    # Min corner → (-1, -1); max corner → (1, 1); center → (0, 0).
    assert out[0].tolist() == pytest.approx([-1.0, -1.0], abs=1e-6)
    assert out[1].tolist() == pytest.approx([1.0, 1.0], abs=1e-6)
    assert out[2].tolist() == pytest.approx([0.0, 0.0], abs=1e-6)


def test_normalize_coords_handles_degenerate_zero_range() -> None:
    """All-coincident points must not divide by zero; output should land
    at the origin (any finite point is fine, but origin is the convention).
    """
    mod = _load_script_module()
    coords = np.array([[3.0, 3.0], [3.0, 3.0]], dtype=np.float32)
    out = mod._normalize_coords(coords)
    assert np.all(np.isfinite(out))
    assert np.allclose(out, np.zeros_like(coords), atol=1e-6)


def test_build_writes_normalized_coords_into_atlas_layout(tmp_path: Path) -> None:
    """End-to-end invariant: every (x, y) in the written JSON must lie in
    ``[-1, 1]``. This is the bug fix's user-visible contract.
    """
    embed_root, manifest, out_dir = _seed_inputs(tmp_path)
    mod = _load_script_module()
    rc = mod.build(
        embeddings_root=embed_root,
        model_id="voyage-3",
        manifest_path=manifest,
        out_dir=out_dir,
        n_neighbors=2,
        random_state=42,
    )
    assert rc == 0
    layout = json.loads((out_dir / "atlas-layout.json").read_text())
    xs = [p["x"] for p in layout["points"]]
    ys = [p["y"] for p in layout["points"]]
    assert min(xs) >= -1.0 and max(xs) <= 1.0, (
        f"x range {(min(xs), max(xs))} escapes regl-scatterplot's "
        "default [-1, 1] camera"
    )
    assert min(ys) >= -1.0 and max(ys) <= 1.0, (
        f"y range {(min(ys), max(ys))} escapes regl-scatterplot's "
        "default [-1, 1] camera"
    )
    # At least one axis should saturate the unit square so we know we're
    # actually scaling to fill, not just clipping into a tiny corner.
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    assert max(span_x, span_y) == pytest.approx(2.0, abs=1e-3)


def test_select_rows_dedupes_augmented_siblings() -> None:
    """Same dedupe rule as ``build_embed_data.py``: when an un-augmented
    row and an augmented row share ``(card_id, page)``, keep the augmented.

    Verified directly against ``_select_rows`` rather than end-to-end so
    the test doesn't have to feed UMAP a degenerate two-point input
    (UMAP fails on N<5 manifolds with disconnected vertices).
    """
    mod = _load_script_module()
    rows = [
        {"card_id": "card_000", "page": 1, "text_sha": "a", "offset": 0},
        {"card_id": "card_001", "page": 1, "text_sha": "b", "offset": 16},
        # Augmented sibling of the first row — should win.
        {
            "card_id": "card_000",
            "page": 1,
            "text_sha": "c",
            "offset": 32,
            "augmented": True,
        },
    ]
    kept = mod._select_rows({"pages": rows})
    keys = {(r["card_id"], int(r["page"]), bool(r.get("augmented"))) for r in kept}
    assert keys == {("card_000", 1, True), ("card_001", 1, False)}
    assert len(kept) == 2
