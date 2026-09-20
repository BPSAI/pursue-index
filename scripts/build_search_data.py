#!/usr/bin/env python3
"""Build the static search payload for the web UI.

Walks ``settings.ocr_dir`` for ``pages.jsonl`` files, joins each page with
its card metadata from ``data/manifests/latest.json``, and writes a single
``web/public/data/pages.json`` array consumable by the MiniSearch island.

Run after ``pursue ocr run`` completes::

    python scripts/build_search_data.py

Genuinely image-only pages (a photograph, illustration, or blank archival
cover — zero base OCR) receive our own operator-reviewed vision-pass
description as their searchable ``text``, drawn from the image-observations
sidecars (see ``pursue_index.embed.image_observations``). This keeps the
static search payload in parity with the embed vectors, which draw the same
text for those pages. (The external alex-zhang42 VLM augment corpus this
script once consumed via ``--augment-from`` was retired 2026-07-11; its file
remains on NAS as a cold-storage reference but is no longer read.)

The output file is intentionally not committed (data/ derivatives belong
on the NAS); CI rebuilds it on each deploy from the OCR output that
gets synced into the runner. For now this is a manual local build that
you commit alongside the manifest, since OCR runs on the workstation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _search_pages import emit_card_pages, emit_observation_only_pages  # noqa: E402

from pursue_index.config import settings  # noqa: E402
from pursue_index.release.shrink_guard import (  # noqa: E402
    add_shrink_args,
    committed_pages_card_ids,
    enforce,
    find_shrink,
    find_uncovered,
    ocr_dir_error,
    shrink_reason,
)

DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_AUDIT_LOG = REPO_ROOT / "data" / "audit-log.jsonl"
DEFAULT_IMAGE_OBS_INDEX = (
    REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json"
)

# Surya emits <b>...</b> and <u>...</u> markup even with math_mode=False; the
# corpus has no markup semantics, so strip these tags from the search payload
# (text between the tags is preserved). Tracked as ocr-gpu-surya follow-up #2.
def _load_manifest_cards(manifest_path: Path) -> list[dict[str, object]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(manifest["cards"])


def _walk_card_pages(
    ocr_dir: Path,
    titles_by_id: dict[str, str],
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Walk OCR cards and emit per-page docs. Returns (docs, cards_seen).

    A card with no OCR output at all — an image card, which has no document to
    read — is emitted afterwards from its observation sidecar alone, since this
    walk can never reach it and that text is the whole of its searchable
    content.
    """
    docs: list[dict[str, object]] = []
    cards_seen = 0
    ocr_card_ids: set[str] = set()
    for card_dir in sorted(ocr_dir.iterdir()) if ocr_dir.exists() else []:
        if not card_dir.is_dir():
            continue
        meta_path = card_dir / "meta.json"
        pages_path = card_dir / "pages.jsonl"
        if not (meta_path.exists() and pages_path.exists()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("status") != "ok":
            continue
        card_id = card_dir.name
        title = titles_by_id.get(card_id)
        if title is None:
            # Card not in the current manifest (e.g. an upstream-removed
            # re-encode whose live successor card_id now carries the content):
            # its OCR dir lingers on NAS but it must not enter the public
            # search index — the site renders cards only from the manifest, so
            # an indexed-but-unlisted card is a search result with no page.
            print(f"  skip (not in manifest): {card_id}", file=sys.stderr)
            continue
        ocr_card_ids.add(card_id)
        cards_seen += 1
        docs.extend(emit_card_pages(card_id, title, pages_path, obs_lookup))

    image_docs, image_cards = emit_observation_only_pages(
        obs_lookup, ocr_card_ids, titles_by_id
    )
    return docs + image_docs, cards_seen + image_cards


def _load_obs_lookup(
    index_path: Path | None,
) -> dict[tuple[str, int], str] | None:
    """Vision-pass text for image-only pages, or ``None`` when unavailable."""
    if index_path is None or not index_path.exists():
        return None
    from pursue_index.embed.image_observations import load_observation_text

    return load_observation_text(index_path) or None


def build(
    ocr_dir: Path,
    manifest_path: Path,
    out_path: Path,
    image_obs_index: Path | None = None,
    *,
    allow_shrink_reason: str | None = None,
    audit_log: Path = DEFAULT_AUDIT_LOG,
) -> int:
    """Materialize the search payload. Returns process exit code.

    Refuses (exit 1, payload untouched) when the rebuild would shrink the
    payload already at ``out_path`` or leave a manifest card without text; see
    ``pursue_index.release.shrink_guard``.
    """
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    unreadable = ocr_dir_error(ocr_dir)
    if unreadable:
        print(f"cannot read the OCR data root: {unreadable}", file=sys.stderr)
        return 1
    obs_lookup = _load_obs_lookup(image_obs_index)
    manifest_cards = _load_manifest_cards(manifest_path)
    titles_by_id = {str(c["card_id"]): str(c["title"]) for c in manifest_cards}
    docs, cards_seen = _walk_card_pages(ocr_dir, titles_by_id, obs_lookup)
    rebuilt_ids = {str(d["card_id"]) for d in docs}
    rc = enforce(
        "build_search_data.py",
        find_shrink(committed_pages_card_ids(out_path), rebuilt_ids),
        find_uncovered(manifest_cards, rebuilt_ids),
        allow_reason=allow_shrink_reason,
        audit_log=audit_log,
    )
    if rc:
        return rc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    size_mb = out_path.stat().st_size / (1024 * 1024)
    obs_pages = sum(
        1 for d in docs if "IMAGE-OBSERVATIONS" in str(d["text"])
    )
    extra = (
        f"; {obs_pages} image-only pages carry vision-pass text"
        if obs_pages else ""
    )
    print(
        f"wrote {out_path} ({size_mb:.1f} MB): {cards_seen} cards, "
        f"{len(docs)} pages{extra}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ocr-dir", type=Path, default=settings.ocr_dir,
        help="Where OCR output cards live (defaults to settings.ocr_dir).",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST_PATH,
        help="Path to the canonical scrape manifest.",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_PATH,
        help="Where to write web/public/data/pages.json.",
    )
    parser.add_argument(
        "--image-observations-index", type=Path,
        default=DEFAULT_IMAGE_OBS_INDEX,
        help=(
            "image-observations index.json. Image-only pages (zero base OCR) "
            "listed there receive our own vision-pass description as their "
            "searchable text. Pass a non-existent path to disable."
        ),
    )
    add_shrink_args(parser, "pages.json")
    args = parser.parse_args()
    allow_shrink_reason = shrink_reason(parser, args)
    return build(
        ocr_dir=args.ocr_dir,
        manifest_path=args.manifest,
        out_path=args.out,
        image_obs_index=args.image_observations_index,
        allow_shrink_reason=allow_shrink_reason,
    )


if __name__ == "__main__":
    sys.exit(main())
