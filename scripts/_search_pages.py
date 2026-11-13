"""Per-page doc emitters for ``build_search_data.py``.

Turns one card's OCR ``pages.jsonl`` rows, or an image card's observation
sidecar, into the search-payload page docs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_leaf(name: str):
    """``pursue_index/<name>.py``, a stdlib-only module, loaded by file path.

    Importing it as ``pursue_index.<name>`` would run the package
    ``__init__`` and its third-party deps first, so this script stays
    importable without the package installed.
    """
    path = Path(__file__).resolve().parents[1] / "src" / "pursue_index" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_pursue_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_published_ocr_text = _load_leaf("page_text").published_ocr_text
# The same one-row-per-page choice the cleaning build makes, so the text
# published for a page is the text its cleaned row was stamped against.
_latest_per_page = _load_leaf("page_rows").latest_per_page


def _clean_text(text: str) -> str:
    # One definition, shared with the cleaned-page provenance check.
    return _published_ocr_text(text)


def emit_observation_only_pages(
    obs_lookup: dict[tuple[str, int], str] | None,
    ocr_card_ids: set[str],
    titles_by_id: dict[str, str],
) -> tuple[list[dict[str, object]], int]:
    """Docs for cards whose only searchable text is an observation.

    A card absent from the current manifest is skipped for the same reason the
    OCR walk skips one: the site renders cards from the manifest, so an indexed
    card with no page is a search result a reader cannot open.
    """
    from pursue_index.embed.image_observations import observation_only_pages

    docs: list[dict[str, object]] = []
    seen: set[str] = set()
    for card_id, page, text in observation_only_pages(obs_lookup, ocr_card_ids):
        title = titles_by_id.get(card_id)
        if title is None:
            print(f"  skip (not in manifest): {card_id}", file=sys.stderr)
            continue
        seen.add(card_id)
        docs.append(
            {
                "id": f"{card_id}-p{page}",
                "card_id": card_id,
                "page": page,
                "title": title,
                "text": text,
                "engine": "vision-observations",
                "confidence": 100,
            }
        )
    return docs, len(seen)


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


def emit_card_pages(
    card_id: str,
    title: str,
    pages_path: Path,
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with pages_path.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    # pages.jsonl is append-only: a re-OCR adds a row for a page that already
    # has one. Publish one row per page, chosen as build_pages_cleaned chooses
    # (latest by generated_at, then file order), so the release gate's
    # per-page provenance compares like with like.
    for row in sorted(_latest_per_page(rows, card_id), key=lambda r: int(r["page"])):
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
