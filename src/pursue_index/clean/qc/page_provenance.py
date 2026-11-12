"""Per-page provenance tying each cleaned page to the OCR text published now.

A cleaned page is trustworthy only if three things agree: the OCR text the
cleanup runner consumed, the OCR row the corpus selects for the page now, and
the text ``pages.json`` publishes for it. ``scripts/build_pages_cleaned.py``
stamps every cleaned row it ships in ``pages-cleaned.json`` with:

* ``ocr_page_sha256`` -- the text hash of the OCR row selected for the page
  from the card's ``pages.jsonl`` (``page_rows.latest_per_page``), hashed as
  the cleanup runner hashes its input into ``input_sha256``
  (``clean.prompt.input_sha256``: the UTF-8 bytes).
* ``ocr_published_sha256`` -- the text hash of what ``pages.json`` publishes
  for that OCR text: ``published_ocr_text`` (the same markup strip
  ``scripts/build_search_data.py`` applies; it imports it from here).
* ``ocr_image_only`` -- true when that published OCR text is blank. Such a
  page is image-only: ``pages.json`` publishes our vision description for
  it (``embed.image_observations``) or nothing, never OCR text.

``scripts/build_qc_coverage.py`` then checks, per judged page and without
the NAS:

1. ``input_sha256 == ocr_page_sha256`` -- the page was cleaned from the OCR
   row the corpus selects now;
2. for a text page, the current pages.json text hashes to
   ``ocr_published_sha256`` -- the site publishes that same OCR text;
3. for an image-only page, the current pages.json text is blank or a vision
   description -- not OCR text the cleaned page never saw.

So a re-OCR is caught whichever side lags: cleaned sidecars that were never
re-run fail (1); a pages.json that was never rebuilt fails (2) or (3).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pursue_index.embed.image_observations import OBSERVATIONS_HEADER

__all__ = [
    "IMAGE_ONLY_KEY",
    "OCR_KEY",
    "PUBLISHED_KEY",
    "ocr_page_provenance",
    "provenance_gaps",
    "published_ocr_text",
    "published_pages",
    "stamp_page_provenance",
    "text_sha256",
]

OCR_KEY = "ocr_page_sha256"
PUBLISHED_KEY = "ocr_published_sha256"
IMAGE_ONLY_KEY = "ocr_image_only"

# Surya emits <b>/<u>/<i> markup even with math_mode=False; the corpus has no
# markup semantics, so pages.json publishes the text between the tags.
_OCR_MARKUP = re.compile(r"</?(?:b|u|i)>")


def published_ocr_text(raw: str) -> str:
    """The text pages.json publishes for a page's raw OCR text."""
    return _OCR_MARKUP.sub("", raw)


def text_sha256(text: object) -> str:
    """sha256 of a page's text: the UTF-8 bytes, ``None`` read as empty."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def ocr_page_provenance(
    selected_rows: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """``{page: {ocr_page_sha256, ocr_published_sha256, ocr_image_only}}`` of
    the OCR rows already selected one per page."""
    out: dict[int, dict[str, Any]] = {}
    for row in selected_rows:
        raw = str(row.get("text") or "")
        published = published_ocr_text(raw)
        out[int(row["page"])] = {
            OCR_KEY: text_sha256(raw),
            PUBLISHED_KEY: text_sha256(published),
            IMAGE_ONLY_KEY: not published.strip(),
        }
    return out


def published_pages(rows: object) -> dict[tuple[str, int], tuple[str, bool]]:
    """``{(card_id, page): (text_sha256, blank_or_vision)}`` of a pages.json
    row list; a malformed row has no page to vouch for and is left out."""
    out: dict[tuple[str, int], tuple[str, bool]] = {}
    for row in rows if isinstance(rows, list) else []:
        try:
            text = str(row.get("text") or "")
            key = (row["card_id"], int(row["page"]))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if not isinstance(key[0], str):
            continue  # a card_id is a string; a list or dict would not even hash
        out[key] = (text_sha256(text), not text.strip() or text.startswith(OBSERVATIONS_HEADER))
    return out


def stamp_page_provenance(
    rows: list[dict], ocr: Mapping[int, Mapping[str, Any]],
) -> list[dict]:
    """Copies of a card's cleaned ``rows`` carrying the three OCR provenance
    fields; a page with no OCR row gets ``""`` hashes (never tied)."""
    missing = {OCR_KEY: "", PUBLISHED_KEY: "", IMAGE_ONLY_KEY: False}
    return [{**row, **ocr.get(int(row["page"]), missing)} for row in rows]


def _row_gaps(row: Mapping[str, Any], current: Mapping[tuple[str, int], tuple[str, bool]],
              asset_name: str) -> list[str]:
    where = f"{row['card_id']} page {row.get('page')}"
    ocr, published = row.get(OCR_KEY), row.get(PUBLISHED_KEY)
    image_only = row.get(IMAGE_ONLY_KEY)
    if not ocr or not published or not isinstance(image_only, bool):
        return [f"{where}: no per-page provenance (rebuild {asset_name})"]
    gaps = []
    if row.get("input_sha256") != ocr:
        gaps.append(f"{where}: cleaned from other OCR text than the page's current OCR row "
                    f"(re-clean it): input {str(row.get('input_sha256'))[:12]}, ocr {str(ocr)[:12]}")
    try:
        now = current.get((row["card_id"], int(row["page"])))
    except (TypeError, ValueError):
        now = None
    if now is None:
        gaps.append(f"{where}: not in pages.json")
    elif image_only and not now[1]:
        gaps.append(f"{where}: pages.json publishes OCR text for a page cleaned as image-only "
                    "(rebuild pages.json or re-clean)")
    elif not image_only and now[0] != published:
        gaps.append(f"{where}: pages.json does not publish the OCR text this page was cleaned "
                    f"from: expected {published[:12]}, published {now[0][:12]}")
    return gaps


def provenance_gaps(
    cleaned_rows: object, current: Mapping[tuple[str, int], tuple[str, bool]],
    card_ids: set[str], asset_name: str = "pages-cleaned.json",
) -> list[str]:
    """One line per cleaned page of ``card_ids`` that cannot be tied to the
    OCR text published now (``current``: ``published_pages`` of the current
    pages.json). ``[]`` when every such page is tied."""
    gaps: list[str] = []
    for row in cleaned_rows if isinstance(cleaned_rows, list) else []:
        if isinstance(row, Mapping) and row.get("card_id") in card_ids:
            gaps += _row_gaps(row, current, asset_name)
    return gaps
