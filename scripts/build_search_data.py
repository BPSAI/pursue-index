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
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_IMAGE_OBS_INDEX = (
    REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json"
)

# Surya emits <b>...</b> and <u>...</u> markup even with math_mode=False; the
# corpus has no markup semantics, so strip these tags from the search payload
# (text between the tags is preserved). Tracked as ocr-gpu-surya follow-up #2.
_SURYA_TAG_RE = re.compile(r"</?(?:b|u|i)>")


def _clean_text(text: str) -> str:
    return _SURYA_TAG_RE.sub("", text)


def _load_titles(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text())
    return {c["card_id"]: c["title"] for c in manifest["cards"]}


def _walk_card_pages(
    ocr_dir: Path,
    titles_by_id: dict[str, str],
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Walk OCR cards and emit per-page docs. Returns (docs, cards_seen)."""
    docs: list[dict[str, object]] = []
    cards_seen = 0
    if not ocr_dir.exists():
        return docs, cards_seen
    for card_dir in sorted(ocr_dir.iterdir()):
        if not card_dir.is_dir():
            continue
        meta_path = card_dir / "meta.json"
        pages_path = card_dir / "pages.jsonl"
        if not (meta_path.exists() and pages_path.exists()):
            continue
        meta = json.loads(meta_path.read_text())
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
        cards_seen += 1
        docs.extend(_emit_card_pages(card_id, title, pages_path, obs_lookup))
    return docs, cards_seen


def _resolve_page_text(
    card_id: str,
    page: int,
    raw_text: str,
    obs_lookup: dict[tuple[str, int], str] | None,
) -> str:
    """Base OCR, or — for a genuinely image-only page (empty base OCR) — our own
    operator-reviewed vision-pass text, kept byte-identical to what the embed
    run hashed for that page so keyword and vector retrieval stay in parity."""
    base = _clean_text(raw_text)
    if not base.strip() and obs_lookup:
        obs = obs_lookup.get((card_id, page))
        if obs:
            return obs
    return base


def _emit_card_pages(
    card_id: str,
    title: str,
    pages_path: Path,
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with pages_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            page = int(row["page"])
            text = _resolve_page_text(
                card_id, page, row["text"], obs_lookup
            )
            out.append(
                {
                    "id": f"{card_id}-p{page}",
                    "card_id": card_id,
                    "page": page,
                    "title": title,
                    "text": text,
                    "engine": row.get("engine", "unknown"),
                    "confidence": row.get("confidence", 0),
                }
            )
    return out


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
) -> int:
    """Materialize the search payload. Returns process exit code."""
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    obs_lookup = _load_obs_lookup(image_obs_index)
    titles_by_id = _load_titles(manifest_path)
    docs, cards_seen = _walk_card_pages(ocr_dir, titles_by_id, obs_lookup)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(docs, ensure_ascii=False))
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
    args = parser.parse_args()
    return build(
        ocr_dir=args.ocr_dir,
        manifest_path=args.manifest,
        out_path=args.out,
        image_obs_index=args.image_observations_index,
    )


if __name__ == "__main__":
    sys.exit(main())
