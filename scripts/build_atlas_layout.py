#!/usr/bin/env python3
"""Build the 2D semantic-browser layout for ``/atlas``.

Reads ``{embeddings_root}/{model_id}/{vectors.bin,index.json}`` (the
native float32 output of ``pursue embed run``), runs UMAP to project the
1024-dim Voyage-3 embeddings into 2D, joins each row's ``card_id`` to
its agency from ``data/manifests/latest.json``, and writes
``web/public/data/atlas-layout.json``.

Wire shape (one entry per indexed page)::

    {
      "model_id": "voyage-3",
      "augmented_by": { ... },        # passthrough from index.json (optional)
      "n": 4119,
      "points": [
        {"card_id": "...", "page": 1, "x": 0.123, "y": -0.456, "agency": "FBI"},
        ...
      ]
    }

Reproducibility: ``random_state=42`` pinned. Re-running on the same
``vectors.bin`` produces identical coordinates so layout shifts are not
a noisy diff in PRs. UMAP version is recorded in
``pyproject.toml::project.optional-dependencies::build-tools`` — bump
when intentionally regenerating.

Float16 vs float32 caveat: UMAP is sensitive to small numerical
perturbations in the input. Running with ``--from-published`` (the
deployed float16 payload) produces coordinates that are *near*, not
identical, to a native float32 run — the per-point delta is small but
nonzero. The deployed ``atlas-layout.json`` should be regenerated from
the native float32 ``vectors.bin`` whenever the NAS is reachable; the
published-payload path is a CI / airgap fallback only.

Run from project root after a fresh embed pass::

    python scripts/build_atlas_layout.py

UMAP at 4,119 × 1024 takes ~30s on a single CPU core. The script is a
build-time tool, not a runtime dep — ``umap-learn`` lives under the
``build-tools`` extra to keep production install footprint small.

Pipeline functions are split out for unit-testability and to keep the
module under the project's 400-line architecture cap. The heavy lifting
(``_load_native_vectors``, ``_select_rows``, ``_filter_vectors``) mirrors
``scripts/build_embed_data.py`` so both publish steps see the same
post-augmentation dedupe.
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

DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "data"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"


def _load_published_vectors(web_data_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read the deployed float16 payload, return ``(arr_f32, index)``.

    Used when running the build off the committed
    ``web/public/data/{embeddings.bin,embed_index.json}`` rather than a
    native embed root — handy in CI / smoke environments that don't have
    the NAS-mounted embed dir. The deployed index is already deduped and
    row-keyed by array index (``offset`` is dropped), so we synthesise
    fake offsets to keep the downstream filter happy.
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
    """Read ``vectors.bin`` (float32) into a contiguous ``[total, dim]`` array.

    ``total`` is derived from the actual file size, not from
    ``index["n"]``. After an augmented embed run, ``vectors.bin`` may
    contain orphan rows whose ``(card_id, page)`` was deduped out of
    ``index.json``; downstream filtering handles that, but we need to
    keep their bytes addressable so the kept rows' ``offset`` values
    still resolve.
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


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Drop un-augmented rows whose ``(card_id, page)`` has an augmented sibling.

    Same dedupe rule used by ``scripts/build_embed_data.py`` so that the
    atlas points and the published embedding payload reference the same
    set of rows.
    """
    augmented_keys = {
        (r["card_id"], int(r["page"])) for r in rows if r.get("augmented")
    }
    return [
        r
        for r in rows
        if r.get("augmented")
        or (r["card_id"], int(r["page"])) not in augmented_keys
    ]


def _select_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    """Return offset-sorted rows after orphan-row dedupe."""
    rows = sorted(index["pages"], key=lambda r: r["offset"])
    return _dedupe_rows(rows)


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

    Imported lazily so the script's import path doesn't pull in
    ``umap-learn`` (and its scikit-learn / numba transitive deps) for
    callers that only want to import helper functions in tests.
    """
    import umap  # type: ignore[import-untyped]

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
        # Pin transform_seed too — UMAP samples a separate RNG for the
        # transform stage when ``random_state`` is set, but pinning both
        # belts-and-braces against future API drift.
        transform_seed=random_state,
    )
    return reducer.fit_transform(arr.astype(np.float32))


def _make_points(
    kept_rows: list[dict[str, Any]],
    coords: np.ndarray,
    agency_map: dict[str, str],
    *,
    coord_precision: int = 4,
) -> list[dict[str, Any]]:
    """Zip kept rows + coords + agency lookup into the wire shape.

    Coordinates are rounded to ``coord_precision`` decimals (default 4)
    — UMAP output is inherently a low-precision projection and the
    extra digits inflate the JSON wire size by ~30% with no perceivable
    rendering benefit.
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
    # Compact separators trim ~10% off the wire size at no loss of fidelity.
    serialized = json.dumps(payload, separators=(",", ":"))
    # Write to ``.tmp`` sibling then ``os.replace`` — POSIX-atomic on the
    # same filesystem, so a crash mid-write can't leave the deployed
    # ``atlas-layout.json`` half-written (the asset is 343 KB; partial
    # writes have shipped corrupt JSON to the browser before).
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
) -> int:
    """Build ``atlas-layout.json``. Returns 0 on success, non-zero on failure.

    Default source is the native embed root; pass ``from_published``
    pointing at ``web/public/data/`` for the deployed float16 payload
    fallback (negligible UMAP-precision delta).
    """
    loaded = _load_source(
        embeddings_root=embeddings_root,
        model_id=model_id,
        from_published=from_published,
    )
    if loaded is None:
        return 1
    arr, index = loaded
    dim = int(index["dim"])
    kept_rows = _select_rows(index)
    arr = _filter_vectors(arr, kept_rows, dim)
    coords = _project_2d(
        arr,
        n_neighbors=min(n_neighbors, max(2, arr.shape[0] - 1)),
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
        f"wrote {out_path} ({len(points)} points, {arr.shape[1]} input dims, "
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
        help=(
            "Read deployed float16 payload from this dir "
            "(web/public/data) instead of the native embed root."
        ),
    )
    return p


def main() -> int:
    # Lazy settings import so the test harness doesn't require .env to be
    # populated — ``build`` accepts explicit paths instead of consulting
    # settings directly.
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
    )


if __name__ == "__main__":
    sys.exit(main())
