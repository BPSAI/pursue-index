#!/usr/bin/env python3
"""Build the lazy-loaded `pages-cleaned.json` mirror for the reader UI.

Walks ``settings.ocr_dir`` for ``pages_cleaned.jsonl`` sidecars, joins each
row with its card metadata, and writes a single
``web/public/data/pages-cleaned.json`` with two top-level keys::

    {
      "meta": {
        "generated_at": "...",
        "source": "pilot-30-cards",
        "cards_covered": ["...", "..."],
        "model_id": "claude-haiku-4-5-20251001",
        "page_count": 123,
        "prompt_sha256": "..."
      },
      "pages": [
        {"id": "<card>-p<n>", "card_id": "...", "page": N,
         "title": "...", "text": "<cleaned>",
         "source_page_sha256": "...",
         "model_id": "...", "prompt_sha256": "...",
         "input_sha256": "...", "output_sha256": "...",
         "generated_at": "..."},
        ...
      ]
    }

The shape mirrors ``pages.json`` so the reader-mode component can index it
the same way — see `web/src/components/CardOcrIsland.tsx`.

``source_page_sha256`` (R7C.15) is the sha256 of the sidecar's
``text_cleaned`` as read, BEFORE this builder's own sanitization clears or
rewrites it for a skipped row (see ``_stamp_source_page_sha256``) -- the
same field name and definition the clean-QC sidecar stamps.
``scripts/build_qc_coverage.py`` recomputes each judged card's digest
from these committed shas, since CI cannot read the NAS sidecars that
would otherwise carry them.

Per-page provenance (``ocr_page_sha256``, ``ocr_published_sha256``,
``ocr_image_only``; see ``pursue_index.clean.qc.page_provenance``) lets the
gate prove each cleaned page was derived from the OCR text pages.json
publishes now.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import hashlib
import json
from datetime import UTC, datetime

from pursue_index.paths import repo_root

REPO_ROOT = repo_root()

from _pages_cleaned_rows import (  # noqa: F401 - the CLEANUP_SKIP_* names are re-exported
    CLEANUP_SKIP_REASONS,
    CLEANUP_SKIP_REQUIRES_TEXT_CLEAR,
    _assert_homogeneous_provenance,
    _normalize_row,
    _sanitize_row_for_mirror,
    _stamp_source_page_sha256,
)

from pursue_index.clean.qc.page_provenance import (
    ocr_page_provenance,
    stamp_page_provenance,
)
from pursue_index.config import settings
from pursue_index.page_rows import latest_per_page
from pursue_index.release.chunked_asset import (
    BUDGET_BYTES,
    asset_exists,
    read_asset_bytes,
    write_asset,
)

DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_PAGES_PATH = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"

def _load_titles(manifest_path: Path) -> dict[str, str]:
    payload = json.loads(manifest_path.read_text())
    return {c["card_id"]: c["title"] for c in payload["cards"]}


def _iter_sidecar(path: Path) -> list[dict]:
    """Read a sidecar JSONL into a list of rows. Tolerates blank lines."""
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Corrupt row — skip rather than crash the whole build.
                continue
    return rows


def _ocr_provenance(card_dir: Path, card_id: str) -> dict[int, dict]:
    """Provenance of the OCR row selected for each page (``page_provenance``)."""
    ocr = card_dir / "pages.jsonl"
    if not ocr.exists():
        return {}
    return ocr_page_provenance(latest_per_page(_iter_sidecar(ocr), card_id))


def _read_pages_json(pages_path: Path | None) -> bytes | None:
    """The (possibly chunked) pages.json this build sits beside, read once so
    the file-level and per-page hashes describe the same bytes."""
    if pages_path is None or not asset_exists(pages_path):
        return None
    return read_asset_bytes(pages_path)


def _dedupe_latest_per_page(
    rows: list[dict], card_id: str = "",
) -> list[dict]:
    """Keep one row per page, latest by (generated_at, file order).

    The rule lives in ``pursue_index.page_rows`` so the model-staleness
    report applies exactly the same selection.
    """
    return latest_per_page(rows, card_id)


def _walk_sidecars(
    ocr_dir: Path, titles: dict[str, str],
) -> tuple[list[dict], list[str]]:
    """Return ``(pages_list, cards_covered)`` — deduped + sanitized.

    Dedupes to one row per page (latest generated_at wins). ALL rows
    ship regardless of ``cleanup_skipped`` value, so page-N in
    pages-cleaned.json keeps pointing at the same
    source page as page-N in pages.json (the UI paginates by array
    index). ``length_divergence`` rows have ``text_cleaned`` cleared so
    raw OCR never ships under the cleaned label —
    ``_sanitize_row_for_mirror`` enforces that.
    """
    pages: list[dict] = []
    covered: list[str] = []
    if not ocr_dir.exists():
        return pages, covered
    for card_dir in sorted(ocr_dir.iterdir()):
        if not card_dir.is_dir():
            continue
        # The manifest, not the filesystem, decides what ships. A card
        # pruned as superseded keeps its sidecars on disk -- pruning does
        # not delete them -- so walking the OCR directory alone shipped
        # 80e36017873c19a1 and aa3097b4c549a67a into this payload with
        # "(unknown)" titles, while every other derived payload correctly
        # excluded them. `titles` is keyed by manifest card_id, so its
        # membership is the authoritative filter.
        if card_dir.name not in titles:
            continue
        sidecar = card_dir / "pages_cleaned.jsonl"
        if not sidecar.exists():
            continue
        rows = _iter_sidecar(sidecar)
        if not rows:
            continue
        card_id = card_dir.name
        rows = _dedupe_latest_per_page(rows, card_id=card_id)
        rows = [_stamp_source_page_sha256(r) for r in rows]
        rows = stamp_page_provenance(rows, _ocr_provenance(card_dir, card_id))
        rows = [_sanitize_row_for_mirror(r) for r in rows]
        if not rows:
            continue
        covered.append(card_id)
        title = titles.get(card_id, "(unknown)")
        for row in rows:
            pages.append(_normalize_row(row, card_id, title))
    return pages, covered


def _meta_block(
    pages: list[dict], covered: list[str], source_tag: str,
) -> dict:
    """Top-level metadata describing the build."""
    _assert_homogeneous_provenance(pages)
    model_id = pages[0]["model_id"] if pages else ""
    prompt_sha = pages[0]["prompt_sha256"] if pages else ""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source_tag,
        "cards_covered": covered,
        "page_count": len(pages),
        "model_id": model_id,
        "prompt_sha256": prompt_sha,
    }


def build(
    ocr_dir: Path,
    manifest_path: Path,
    out_path: Path,
    source_tag: str,
    budget_bytes: int = BUDGET_BYTES,
    pages_path: Path | None = None,
) -> int:
    """Materialize the deployed mirror. Returns process exit code.

    ``pages_path`` is the pages.json this run sits beside: its sha256 is
    recorded as ``meta.pages_json_sha256``, a record of which pages.json the
    build used. The coverage gate does not read it; it checks provenance per
    page (``ocr_page_sha256`` / ``ocr_published_sha256``).
    """
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    titles = _load_titles(manifest_path)
    pages_bytes = _read_pages_json(pages_path)
    pages, covered = _walk_sidecars(ocr_dir, titles)
    meta = _meta_block(pages, covered, source_tag)
    if pages_bytes is not None:
        meta["pages_json_sha256"] = hashlib.sha256(pages_bytes).hexdigest()
    payload = {"meta": meta, "pages": pages}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = write_asset(
        out_path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), budget=budget_bytes
    )
    size_kb = sum(p.stat().st_size for p in written) / 1024
    print(
        f"wrote {out_path} ({size_kb:.1f} KB): "
        f"{len(covered)} cards, {len(pages)} pages [source={source_tag}]"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ocr-dir", type=Path, default=settings.ocr_dir,
        help="Where per-card sidecars live (defaults to settings.ocr_dir).",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST_PATH,
        help="Path to the canonical scrape manifest.",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_PATH,
        help="Output path for pages-cleaned.json.",
    )
    parser.add_argument(
        "--source-tag", type=str, default="pilot-30-cards",
        help="Label embedded in `meta.source` (e.g. pilot-30-cards or full-corpus).",
    )
    parser.add_argument(
        "--pages", type=Path, default=DEFAULT_PAGES_PATH,
        help="pages.json this build sits beside; its sha256 is recorded as provenance.",
    )
    args = parser.parse_args()
    return build(
        ocr_dir=args.ocr_dir,
        manifest_path=args.manifest,
        out_path=args.out,
        source_tag=args.source_tag,
        pages_path=args.pages,
    )


if __name__ == "__main__":
    sys.exit(main())
