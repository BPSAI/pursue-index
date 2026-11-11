"""Per-page provenance tying each cleaned page to the OCR text published now.

``scripts/build_pages_cleaned.py`` stamps two hashes on every cleaned row it
ships in ``pages-cleaned.json``:

* ``ocr_page_sha256`` -- the text hash of the OCR row the build selected for
  the page from the card's ``pages.jsonl`` (``page_rows.latest_per_page``),
  hashed exactly as the cleanup runner hashes its input into
  ``input_sha256`` (``clean.prompt.input_sha256``: the UTF-8 bytes).
* ``pages_json_text_sha256`` -- the text hash of the page's row in the
  ``pages.json`` the build sat beside.

``scripts/build_qc_coverage.py`` then proves, per judged page and without the
NAS, that the cleaned page was derived from that OCR row (``input_sha256 ==
ocr_page_sha256``) and that the page's pages.json text has not changed since
(``pages_json_text_sha256`` equals the current text hash). A file-level hash
of pages.json cannot do this: after a same-page-count re-OCR, a rebuild from
cleaned sidecars that were never re-run records the new file hash while its
pages still carry the old cleaning.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "OCR_KEY",
    "PAGES_JSON_KEY",
    "ocr_page_shas",
    "provenance_gaps",
    "stamp_page_provenance",
    "text_sha256",
    "text_shas_by_page",
]

OCR_KEY = "ocr_page_sha256"
PAGES_JSON_KEY = "pages_json_text_sha256"


def text_sha256(text: object) -> str:
    """sha256 of a page's text: the UTF-8 bytes, ``None`` read as empty."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def ocr_page_shas(selected_rows: Iterable[Mapping[str, Any]]) -> dict[int, str]:
    """``{page: text_sha256}`` of the OCR rows already selected one per page."""
    return {int(r["page"]): text_sha256(r.get("text", "")) for r in selected_rows}


def text_shas_by_page(rows: object) -> dict[tuple[str, int], str]:
    """``{(card_id, page): text_sha256}`` of a pages.json row list; a
    malformed row has no page to vouch for and is left out."""
    out: dict[tuple[str, int], str] = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            out[(row["card_id"], int(row["page"]))] = text_sha256(row.get("text", ""))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


def stamp_page_provenance(
    rows: list[dict], ocr_shas: Mapping[int, str],
    pages_json_shas: Mapping[tuple[str, int], str] | None, card_id: str,
) -> list[dict]:
    """Copies of a card's cleaned ``rows`` carrying ``ocr_page_sha256`` and,
    when a pages.json was given, ``pages_json_text_sha256`` (``""`` when the
    source has no row for the page)."""
    out = []
    for row in rows:
        page = int(row["page"])
        stamped = {**row, OCR_KEY: ocr_shas.get(page, "")}
        if pages_json_shas is not None:
            stamped[PAGES_JSON_KEY] = pages_json_shas.get((card_id, page), "")
        out.append(stamped)
    return out


def _row_gaps(row: Mapping[str, Any], current: Mapping[tuple[str, int], str],
              asset_name: str) -> list[str]:
    where = f"{row['card_id']} page {row.get('page')}"
    ocr, recorded = row.get(OCR_KEY), row.get(PAGES_JSON_KEY)
    if not ocr or not isinstance(recorded, str):
        return [f"{where}: no per-page provenance (rebuild {asset_name})"]
    gaps = []
    if row.get("input_sha256") != ocr:
        gaps.append(f"{where}: cleaned from other OCR text than the page's current OCR row "
                    f"(re-clean it): input {str(row.get('input_sha256'))[:12]}, ocr {str(ocr)[:12]}")
    try:
        now = current.get((row["card_id"], int(row["page"])), "")
    except (TypeError, ValueError):
        now = ""
    if recorded != now:
        gaps.append(f"{where}: pages.json text changed since {asset_name} was built: "
                    f"recorded {recorded[:12] or '(none)'}, current {now[:12] or '(none)'}")
    return gaps


def provenance_gaps(
    cleaned_rows: object, current: Mapping[tuple[str, int], str], card_ids: set[str],
    asset_name: str = "pages-cleaned.json",
) -> list[str]:
    """One line per cleaned page of ``card_ids`` that cannot be tied to the
    OCR text published now (``current``: ``text_shas_by_page`` of the current
    pages.json). ``[]`` when every such page is tied."""
    gaps: list[str] = []
    for row in cleaned_rows if isinstance(cleaned_rows, list) else []:
        if isinstance(row, Mapping) and row.get("card_id") in card_ids:
            gaps += _row_gaps(row, current, asset_name)
    return gaps
