#!/usr/bin/env python3
"""Build the 2D semantic-browser layout for ``/atlas``.

Reads ``{embeddings_root}/{model_id}/{vectors.bin,index.json}`` (native
float32 from ``pursue embed run``), runs UMAP to project Voyage-3
embeddings into 2D, normalizes coords into ``[-1, 1]`` (regl-scatterplot
camera contract), joins agency from ``data/manifests/latest.json``, and
writes ``web/public/data/atlas-layout.json``.

Wire shape::

    {"model_id": "voyage-3", "augmented_by": {...}, "n": 4119,
     "points": [{"card_id": "...", "page": 1, "x": 0.12, "y": -0.45,
                 "agency": "FBI"}, ...]}

``random_state=42`` is pinned for reproducibility. ``--from-published``
reads the deployed float16 payload as a CI / airgap fallback (small
nonzero precision delta vs native float32). Row selection is shared with
``scripts/build_embed_data.py`` (``pursue_index.embed.publish``) so the
atlas plots exactly the rows the chat payload publishes: one per
``(card_id, page)``, and only for pages with text in ``pages.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.embed.publish import (  # noqa: E402
    load_embed_eligible_keys,
    select_publish_rows,
)

DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "data"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"


def _load_published_vectors(web_data_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read deployed float16 payload, return ``(arr_f32, index)``.

    CI / airgap fallback for when the NAS-mounted embed root is absent.
    The deployed index is row-keyed by array index (``offset`` dropped),
    so synthetic offsets are emitted to keep ``_filter_vectors`` happy.
    """
    idx_path = web_data_dir / "embed_index.json"
    bin_path = web_data_dir / "embeddings.bin"
    index = json.loads(idx_path.read_text())
    dim = int(index["dim"])
    raw = bin_path.read_bytes()
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


def build(
    *,
    embeddings_root: Path,
    model_id: str,
    manifest_path: Path,
    out_dir: Path,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
    from_published: Path | None = None,
    pages_json: Path | None = None,
) -> int:
    """Build ``atlas-layout.json``. Returns 0 on success, non-zero on failure.

    Default source is the native embed root; pass ``from_published``
    pointing at ``web/public/data/`` for the deployed float16 payload
    fallback (negligible UMAP-precision delta). ``pages_json`` supplies the
    publish-eligibility gate and defaults to the source directory's copy.
    """
    pages_path = pages_json or ((from_published or out_dir) / "pages.json")
    if not pages_path.exists():
        print(
            f"pages.json missing at {pages_path}; cannot check publish "
            "eligibility. Build it first (scripts/build_search_data.py).",
            file=sys.stderr,
        )
        return 1
    loaded = _load_source(
        embeddings_root=embeddings_root,
        model_id=model_id,
        from_published=from_published,
    )
    if loaded is None:
        return 1
    arr, index = loaded
    kept_rows, coords = _project_and_normalize(
        arr,
        index,
        load_embed_eligible_keys(pages_path),
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    agency_map = _load_agency_map(manifest_path)
    points = _make_points(kept_rows, coords, agency_map)
    out_path = out_dir / "atlas-layout.json"
    _write_layout(
        out_path,
        model_id=str(index.get("model_id", model_id)),
        points=points,
        augmented_by=index.get("augmented_by"),
    )
    print(
        f"wrote {out_path} ({len(points)} points, "
        f"random_state={random_state})"
    )
    return 0


def _build_parser(default_embeddings_root: Path, default_model: str) -> argparse.ArgumentParser:
    """Argparse setup, factored out so ``main`` stays under the 50-line cap."""
    p = argparse.ArgumentParser(
        description="Build atlas-layout.json for the /atlas semantic browser."
    )
    p.add_argument(
        "--embeddings-root",
        type=Path,
        default=default_embeddings_root,
        help="Root containing per-model dirs (defaults to PURSUE data_root/embeddings).",
    )
    p.add_argument("--model", default=default_model, help="Model id to project.")
    p.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to manifests/latest.json for agency lookup.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Where to write atlas-layout.json.",
    )
    p.add_argument(
        "--n-neighbors", type=int, default=15, help="UMAP n_neighbors (default 15)."
    )
    p.add_argument(
        "--min-dist", type=float, default=0.1, help="UMAP min_dist (default 0.1)."
    )
    p.add_argument(
        "--random-state", type=int, default=42, help="Seed for reproducibility."
    )
    p.add_argument(
        "--from-published",
        type=Path,
        default=None,
        help="Read deployed float16 payload from this dir (web/public/data).",
    )
    p.add_argument(
        "--pages-json",
        type=Path,
        default=None,
        help="pages.json used for publish eligibility (default: source dir).",
    )
    return p


def main() -> int:
    # Lazy settings import keeps the test harness from requiring .env.
    from pursue_index.config import settings

    args = _build_parser(settings.embeddings_dir, settings.embed_model).parse_args()
    return build(
        embeddings_root=args.embeddings_root,
        model_id=args.model,
        manifest_path=args.manifest,
        out_dir=args.out_dir,
        n_neighbors=args.n_neighbors,
        min_dist=args.min_dist,
        random_state=args.random_state,
        from_published=args.from_published,
        pages_json=args.pages_json,
    )


if __name__ == "__main__":
    sys.exit(main())
