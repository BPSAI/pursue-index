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
         "model_id": "...", "prompt_sha256": "...",
         "input_sha256": "...", "output_sha256": "...",
         "generated_at": "..."},
        ...
      ]
    }

The shape mirrors ``pages.json`` so the reader-mode component can index it
the same way — see `web/src/components/CardOcrIsland.tsx`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"

# Canonical list of ``cleanup_skipped`` reasons. Mirrors
# the TS-side ``CLEANUP_SKIP_REASONS`` in
# ``web/src/components/cleaned-pages.ts`` — single-source-of-truth on
# each side of the JSON boundary so a future fourth reason is a
# one-line add on each side.
CLEANUP_SKIP_REASONS = frozenset(
    {"empty_input", "length_divergence", "content_filter"}
)

# Reasons where ``text_cleaned`` must be cleared (and ``output_sha256``
# rehashed) before the row ships in the mirror. ``empty_input`` rows
# already have empty text; the other two carry a raw-OCR fallback or
# unexpected payload from the model that MUST NOT ship under the
# "cleaned" label.
CLEANUP_SKIP_REQUIRES_TEXT_CLEAR = frozenset(
    {"length_divergence", "content_filter"}
)


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


def _dedupe_latest_per_page(
    rows: list[dict], card_id: str = "",
) -> list[dict]:
    """Keep one row per page, latest by (generated_at, file order).

    Append-only sidecars accumulate duplicates after re-runs. Also
    tolerate corrupt rows whose ``page`` is missing or non-numeric —
    log a structured warning to stderr and skip, matching
    ``_iter_sidecar``'s "skip bad JSON, don't crash the build" stance.
    """
    by_page: dict[int, dict] = {}
    for idx, row in enumerate(rows):
        # A missing ``page`` field is a corrupt row, not page 0 (issue
        # #38). Treating absence as 0 used to silently emit garbage
        # rows into pages-cleaned.json at page 0 and break the
        # index-by-page-N navigation contract in CardReaderView. Skip
        # + log instead.
        raw_page = row.get("page")
        if raw_page is None:
            print(
                f"warning clean.build.skip_missing_page "
                f"card_id={card_id} row_index={idx}",
                file=sys.stderr,
            )
            continue
        try:
            page = int(raw_page)
        except (ValueError, TypeError):
            print(
                f"warning clean.build.skip_corrupt_row "
                f"card_id={card_id} row_index={idx} "
                f"bad_page={raw_page!r}",
                file=sys.stderr,
            )
            continue
        prior = by_page.get(page)
        if prior is None:
            by_page[page] = {"row": row, "ts": row.get("generated_at", ""), "i": idx}
            continue
        if (row.get("generated_at", ""), idx) >= (prior["ts"], prior["i"]):
            by_page[page] = {"row": row, "ts": row.get("generated_at", ""), "i": idx}
    return [entry["row"] for entry in by_page.values()]


def _sanitize_row_for_mirror(row: dict) -> dict:
    """Return a copy of ``row`` safe to ship in the cleaned mirror.

    ALL rows are now preserved regardless of ``cleanup_skipped``
    value, so ``pages-cleaned.json`` keeps the same
    page sequence as ``pages.json``. The UI paginates by array index
    (``pages[activePage-1]`` in ``CardReaderView``) — dropping any row
    shifts every later page's position and breaks deep links like
    ``#page-7`` plus citations into the cleaned mirror.

    For ``length_divergence`` rows specifically, the sidecar holds the
    *raw* OCR as a model-failure fallback. We MUST NOT ship that under
    the ``text_cleaned`` label: clear it to "" so the field stays
    semantically clean. The ``cleanup_skipped`` flag is propagated so
    the UI can render an appropriate "[Cleanup unavailable]" notice.
    ``empty_input`` rows already have empty text; preserved as-is.

    ``content_filter`` rows (the third skip reason) follow the same
    contract as ``length_divergence``: the runner already writes empty
    text for them, but defensively clear + rehash here so a future
    runner change can never leak un-cleaned text under the "cleaned"
    label. Cost-of-defense: one extra hash per filtered row, which is
    rare enough not to matter.

    The runner stored ``output_sha256`` against the raw OCR
    fallback. After we clear ``text_cleaned`` we MUST recompute
    ``output_sha256`` against the new (empty) text — otherwise the
    shipped row violates the provenance contract that ``output_sha256``
    matches the shipped ``text``. Mirrors the runner's hashing
    (``src/pursue_index/clean/prompt.py::output_sha256``).
    """
    skipped = row.get("cleanup_skipped")
    if skipped in CLEANUP_SKIP_REQUIRES_TEXT_CLEAR:
        sanitized = dict(row)
        sanitized["text_cleaned"] = ""
        sanitized["output_sha256"] = hashlib.sha256(b"").hexdigest()
        return sanitized
    return row


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
        sidecar = card_dir / "pages_cleaned.jsonl"
        if not sidecar.exists():
            continue
        rows = _iter_sidecar(sidecar)
        if not rows:
            continue
        card_id = card_dir.name
        rows = _dedupe_latest_per_page(rows, card_id=card_id)
        rows = [_sanitize_row_for_mirror(r) for r in rows]
        if not rows:
            continue
        covered.append(card_id)
        title = titles.get(card_id, "(unknown)")
        for row in rows:
            pages.append(_normalize_row(row, card_id, title))
    return pages, covered


def _normalize_row(row: dict, card_id: str, title: str) -> dict:
    """Coerce a sidecar row to the deployed-mirror page shape.

    Propagates ``cleanup_skipped`` only when it has a truthy value so
    "normal" rows stay free of the field (smaller payload, simpler
    UI-side checks like ``if (page.cleanup_skipped)``).

    Callers are expected to have already filtered rows missing the
    ``page`` field via ``_dedupe_pages`` (closes issue #38). If a row
    reaches here without a ``page`` field, a ``ValueError`` propagates
    so the failure is loud rather than silently emitting a page-0 row.
    """
    raw_page = row.get("page")
    if raw_page is None:
        raise ValueError(
            f"missing 'page' field on row for card_id={card_id}; "
            "should have been filtered by _dedupe_pages"
        )
    page = int(raw_page)
    out: dict = {
        "id": row.get("id") or f"{card_id}-p{page}",
        "card_id": card_id,
        "page": page,
        "title": title,
        "text": row.get("text_cleaned", ""),
        "model_id": row.get("model_id", ""),
        "prompt_sha256": row.get("prompt_sha256", ""),
        "input_sha256": row.get("input_sha256", ""),
        "output_sha256": row.get("output_sha256", ""),
        "generated_at": row.get("generated_at", ""),
    }
    skipped = row.get("cleanup_skipped")
    if skipped:
        out["cleanup_skipped"] = skipped
    return out


def _assert_homogeneous_provenance(pages: list[dict]) -> None:
    """Fail loudly when model_id or prompt_sha256 varies across rows.

    Meta records a single value from the first row, so a mixed build
    would misrepresent provenance.
    """
    if not pages:
        return
    model_ids = {p.get("model_id", "") for p in pages}
    prompt_shas = {p.get("prompt_sha256", "") for p in pages}
    if len(model_ids) > 1:
        raise ValueError(
            f"mixed model_id values in sidecars: {sorted(model_ids)}. "
            "Re-clean affected cards or split the build by model."
        )
    if len(prompt_shas) > 1:
        raise ValueError(
            f"mixed prompt_sha256 values in sidecars: {sorted(prompt_shas)}. "
            "Re-clean affected cards or split the build by prompt revision."
        )


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
) -> int:
    """Materialize the deployed mirror. Returns process exit code."""
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    titles = _load_titles(manifest_path)
    pages, covered = _walk_sidecars(ocr_dir, titles)
    payload = {"meta": _meta_block(pages, covered, source_tag), "pages": pages}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False))
    size_kb = out_path.stat().st_size / 1024
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
    args = parser.parse_args()
    return build(
        ocr_dir=args.ocr_dir,
        manifest_path=args.manifest,
        out_path=args.out,
        source_tag=args.source_tag,
    )


if __name__ == "__main__":
    sys.exit(main())
