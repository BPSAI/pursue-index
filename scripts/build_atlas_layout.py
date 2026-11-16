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

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
from typing import Any

from pursue_index.paths import repo_root

REPO_ROOT = repo_root()

from _atlas_parts import (
    _load_agency_map,
    _load_source,
    _make_points,
    _project_and_normalize,
    _write_layout,
)

from pursue_index.embed.publish import (
    load_embed_eligible_keys,
)
from pursue_index.release.chunked_asset import (
    asset_exists,
)

DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "data"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"

# Mirrors AGENCY_ORDER in web/src/components/atlas-helpers.ts. Every agency
# this build emits must have a slot there (color + legend label) or its
# points silently render as grey UNKNOWN with no legend entry — see
# ``unmapped_agencies_in_layout``. Keep both lists in sync when a new
# agency enters the manifest.
AGENCY_ORDER = (
    "Department of War",
    "FBI",
    "NASA",
    "Department of State",
    "CIA",
    "Department of Energy",
    "Executive Office of the President",
    "Intelligence Community Agency",
    "Local Law Enforcement",
    "Office of the Director of National Intelligence",
    "U.S. Government",
)


def unmapped_agencies_in_layout(layout: dict[str, Any]) -> set[str]:
    """Agencies in ``layout["points"]`` with no ``AGENCY_ORDER`` slot.

    ``"UNKNOWN"`` is the documented fallback for cards missing from the
    manifest (see ``_make_points``) and already has a color/legend slot —
    it is not itself a violation. Callable both as a build()-time guard
    and directly against any layout dict (fixture or committed).
    """
    return {
        p["agency"]
        for p in layout.get("points", [])
        if p.get("agency") not in AGENCY_ORDER and p.get("agency") != "UNKNOWN"
    }


def _pages_json_present(pages_path: Path) -> bool:
    """pages.json gates publish eligibility; say so and refuse when it is missing."""
    if asset_exists(pages_path):
        return True
    print(
        f"pages.json missing at {pages_path}; cannot check publish "
        "eligibility. Build it first (scripts/build_search_data.py).",
        file=sys.stderr,
    )
    return False


def _refuse_unmapped_agencies(points: list[dict[str, Any]]) -> bool:
    """Print and return True when a point's agency has no AGENCY_ORDER slot."""
    unmapped = unmapped_agencies_in_layout({"points": points})
    if unmapped:
        print(
            f"agencies with no AGENCY_ORDER slot: {sorted(unmapped)} — add them "
            "to AGENCY_ORDER in both scripts/build_atlas_layout.py and "
            "web/src/components/atlas-helpers.ts, then add a matching color "
            "token in web/src/styles/global.css and update "
            "tests/unit/test_a11y_contrast.py",
            file=sys.stderr,
        )
    return bool(unmapped)


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
    if not _pages_json_present(pages_path):
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
    if _refuse_unmapped_agencies(points):
        return 1
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
