"""Per-row shaping for ``build_pages_cleaned.py``: skip reasons, the
``source_page_sha256`` stamp, the mirror-safe sanitize, the deployed row
shape and the one-model/one-prompt provenance check.

Split out of ``build_pages_cleaned.py`` to keep it under the arch limits.
Imported by path from ``scripts/`` (the script puts its own directory on
``sys.path`` first).
"""

from __future__ import annotations

import hashlib

from pursue_index.clean.qc.page_provenance import IMAGE_ONLY_KEY, OCR_KEY, PUBLISHED_KEY
from pursue_index.vendor.judged_pages_digest import page_sha256

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


def _stamp_source_page_sha256(row: dict) -> dict:
    """Return a copy of ``row`` carrying ``source_page_sha256``.

    Hashed from the sidecar's ``text_cleaned`` as read -- BEFORE
    ``_sanitize_row_for_mirror`` clears or rewrites it for a skipped row.
    This is the one definition (via the vendored ``page_sha256``) a
    sanitized page's un-sanitized text hashes to, matching what
    the clean-QC sidecar stamps against the same field (R7C.14
    / R7C.15): the coverage builder recomputes a card's judged-pages
    digest from these committed shas since CI cannot read the NAS
    sidecars that would otherwise carry them.
    """
    sanitized = dict(row)
    sanitized["source_page_sha256"] = page_sha256(row.get("text_cleaned", ""))
    return sanitized


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
        "source_page_sha256": row.get("source_page_sha256", ""),
        OCR_KEY: row.get(OCR_KEY, ""),
        PUBLISHED_KEY: row.get(PUBLISHED_KEY, ""),
        IMAGE_ONLY_KEY: bool(row.get(IMAGE_ONLY_KEY, False)),
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
