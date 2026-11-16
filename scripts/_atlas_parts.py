"""Parts of ``build_atlas_layout.py``: load the page vectors (native embed
root or the published float16 payload), keep the publish-eligible rows, the
card to agency map, the 2-D UMAP projection normalized to [-1, 1], the point
records, and the layout writer.

Split out of ``build_atlas_layout.py`` to keep it under the arch limits.
Imported by path from ``scripts/`` (the script puts its own directory on
``sys.path`` first).
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

from pursue_index.embed.publish import select_publish_rows
from pursue_index.release.chunked_asset import read_asset_bytes, read_asset_json


def _load_published_vectors(web_data_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read deployed float16 payload, return ``(arr_f32, index)``.

    CI / airgap fallback for when the NAS-mounted embed root is absent.
    The deployed index is row-keyed by array index (``offset`` dropped),
    so synthetic offsets are emitted to keep ``_filter_vectors`` happy.
    """
    idx_path = web_data_dir / "embed_index.json"
    bin_path = web_data_dir / "embeddings.bin"
    index = read_asset_json(idx_path)
    dim = int(index["dim"])
    raw = read_asset_bytes(bin_path)
    if len(raw) % (dim * 2) != 0:
        raise RuntimeError(
            f"embeddings.bin size {len(raw)} not a multiple of dim*2 ({dim * 2})"
        )
    arr = np.frombuffer(raw, dtype="<f2").astype(np.float32).reshape(-1, dim)
    pages = []
    for i, page_pair in enumerate(index["pages"]):
        card_id, page = page_pair
        pages.append(
            {
                "card_id": str(card_id),
                "page": int(page),
                # Synthetic offset so ``_filter_vectors`` indexing works.
                "offset": i * dim * 4,
            }
        )
    synthesised = {
        "model_id": str(index.get("model_id", "")),
        "dim": dim,
        "n": len(pages),
        "pages": pages,
    }
    if "augmented_by" in index:
        synthesised["augmented_by"] = index["augmented_by"]
    return arr, synthesised


def _load_native_vectors(in_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read ``vectors.bin`` (float32) into a ``[total, dim]`` array.

    ``total`` is derived from file size, not ``index["n"]`` — augmented
    embed runs leave orphan rows in ``vectors.bin`` whose ``(card_id,
    page)`` was deduped out of ``index.json``; their bytes must stay
    addressable so kept rows' ``offset`` values still resolve.
    """
    index = json.loads((in_dir / "index.json").read_text())
    dim = int(index["dim"])
    raw = (in_dir / "vectors.bin").read_bytes()
    if len(raw) % (dim * 4) != 0:
        raise RuntimeError(
            f"vectors.bin size {len(raw)} not a multiple of dim*4 ({dim * 4})"
        )
    total = len(raw) // (dim * 4)
    if total < int(index["n"]):
        raise RuntimeError(
            f"vectors.bin holds {total} vectors but index references {index['n']} rows"
        )
    floats = struct.unpack(f"<{total * dim}f", raw)
    arr = np.array(floats, dtype=np.float32).reshape(total, dim)
    return arr, index


def _select_rows(
    index: dict[str, Any], eligible: set[tuple[str, int]]
) -> list[dict[str, Any]]:
    """Offset-sorted, publish-eligible, one row per ``(card_id, page)``.

    Shares ``select_publish_rows`` with ``scripts/build_embed_data.py`` so
    atlas points and the published embedding payload reference the same rows.
    """
    return select_publish_rows(index["pages"], eligible)


def _filter_vectors(arr: np.ndarray, kept_rows: list[dict], dim: int) -> np.ndarray:
    """Slice the raw ``[total, dim]`` array to just the rows we kept."""
    indices = [r["offset"] // (dim * 4) for r in kept_rows]
    return arr[indices]


def _load_agency_map(manifest_path: Path) -> dict[str, str]:
    """Build ``card_id → agency`` from ``manifests/latest.json``."""
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text())
    out: dict[str, str] = {}
    for card in manifest.get("cards", []):
        cid = card.get("card_id")
        agency = card.get("agency")
        if cid and agency:
            out[str(cid)] = str(agency)
    return out


def _project_2d(
    arr: np.ndarray,
    *,
    n_neighbors: int,
    min_dist: float,
    random_state: int,
) -> np.ndarray:
    """Run UMAP to project ``arr`` into 2D.

    Imported lazily so tests that only need helpers don't pull in
    ``umap-learn`` (scikit-learn / numba transitive deps).
    ``transform_seed`` is pinned alongside ``random_state`` against
    future UMAP API drift in the transform-stage RNG.
    """
    import umap  # type: ignore[import-untyped]

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
        transform_seed=random_state,
    )
    return reducer.fit_transform(arr.astype(np.float32))


def _normalize_coords(coords: np.ndarray) -> np.ndarray:
    """Scale + center 2D coords into the ``[-1, 1]`` unit square.

    regl-scatterplot's default camera frames ``[-1, 1]`` on both axes;
    raw UMAP output (tens of units wide, off-origin) renders off-screen.
    Uniform scaling by the wider axis preserves UMAP's aspect ratio.
    Zero-range input collapses to the origin (no divide-by-zero).
    """
    x_min, x_max = float(coords[:, 0].min()), float(coords[:, 0].max())
    y_min, y_max = float(coords[:, 1].min()), float(coords[:, 1].max())
    x_center = (x_max + x_min) / 2.0
    y_center = (y_max + y_min) / 2.0
    half_range = max(x_max - x_min, y_max - y_min) / 2.0
    if half_range < 1e-12:
        return np.zeros_like(coords)
    out = np.empty_like(coords)
    out[:, 0] = (coords[:, 0] - x_center) / half_range
    out[:, 1] = (coords[:, 1] - y_center) / half_range
    return out


def _load_source(
    *,
    embeddings_root: Path,
    model_id: str,
    from_published: Path | None,
) -> tuple[np.ndarray, dict[str, Any]] | None:
    """Resolve the embedding source. Returns ``None`` and prints to
    stderr if the native source is missing — caller maps that to rc=1.
    """
    if from_published is not None:
        return _load_published_vectors(from_published)
    in_dir = embeddings_root / model_id
    if not (in_dir / "index.json").exists():
        print(f"index.json missing in {in_dir}", file=sys.stderr)
        return None
    return _load_native_vectors(in_dir)


def _project_and_normalize(
    arr: np.ndarray,
    index: dict[str, Any],
    eligible: set[tuple[str, int]],
    *,
    n_neighbors: int,
    min_dist: float,
    random_state: int,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    """Filter to kept rows, run UMAP, normalize to [-1, 1].

    Returns ``(kept_rows, normalized_coords)``. Normalization is required
    so regl-scatterplot's default unit-square camera frames the cluster.
    """
    dim = int(index["dim"])
    kept_rows = _select_rows(index, eligible)
    filtered = _filter_vectors(arr, kept_rows, dim)
    coords = _project_2d(
        filtered,
        n_neighbors=min(n_neighbors, max(2, filtered.shape[0] - 1)),
        min_dist=min_dist,
        random_state=random_state,
    )
    return kept_rows, _normalize_coords(coords)


def _make_points(
    kept_rows: list[dict[str, Any]],
    coords: np.ndarray,
    agency_map: dict[str, str],
    *,
    coord_precision: int = 4,
) -> list[dict[str, Any]]:
    """Zip kept rows + coords + agency lookup into the wire shape.

    Coords are rounded to ``coord_precision`` decimals (default 4) —
    extra digits inflate JSON wire size by ~30% with no rendering gain.
    """
    points: list[dict[str, Any]] = []
    for row, (x, y) in zip(kept_rows, coords, strict=True):
        cid = str(row["card_id"])
        points.append(
            {
                "card_id": cid,
                "page": int(row["page"]),
                "x": round(float(x), coord_precision),
                "y": round(float(y), coord_precision),
                "agency": agency_map.get(cid, "UNKNOWN"),
            }
        )
    return points


def _write_layout(
    out_path: Path,
    *,
    model_id: str,
    points: list[dict[str, Any]],
    augmented_by: dict[str, Any] | None,
) -> None:
    payload: dict[str, Any] = {
        "model_id": model_id,
        "n": len(points),
        "points": points,
    }
    if augmented_by is not None:
        payload["augmented_by"] = augmented_by
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Compact separators trim ~10% off wire size; .tmp + os.replace is
    # POSIX-atomic so a crash mid-write can't ship half-written JSON
    # (the deployed asset is 343 KB — partial writes have corrupted it).
    serialized = json.dumps(payload, separators=(",", ":"))
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(serialized)
    os.replace(tmp_path, out_path)
