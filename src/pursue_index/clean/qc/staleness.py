"""Digest staleness check against the clean-QC bundle (R7C.15).

``pursue_index.clean.qc.coverage`` marked a card ``judged`` whenever the
clean-QC bundle's ``page_count`` matched the card's current page count --
a re-OCR or re-clean that changed page CONTENTS without changing the page
COUNT stayed judged, undetected, because CI cannot read the NAS sidecars
that would otherwise carry each page's sha. This module recomputes the
bundle's per-card ``judged_pages_digest`` from the ``source_page_sha256``
values ``scripts/build_pages_cleaned.py`` commits into
``pages-cleaned.json``, using the vendored, dependency-free
:func:`pursue_index.vendor.judged_pages_digest.judged_pages_digest` --
the one implementation this repo and the clean-QC stage both compute over.

A card whose bundle entry carries no digest (an older bundle, published
before this field existed) or whose committed page shas are incomplete is
left unverifiable rather than flagged stale -- :func:`is_stale` returns
``False`` and the legacy page-count-only classification stands.
"""

from __future__ import annotations

from collections.abc import Mapping

from pursue_index.vendor.judged_pages_digest import judged_pages_digest


def card_page_shas(
    pages_cleaned: Mapping[str, object], problems: list[str] | None = None,
) -> dict[str, dict[int, str]]:
    """``{card_id: {page: source_page_sha256}}`` from ``pages-cleaned.json``.

    Rows without a (truthy) ``source_page_sha256`` are omitted -- an older
    payload built before R7C.15 carries none, and a card with any page
    missing its sha is then incomplete, which :func:`is_stale` treats as
    unverifiable.

    A malformed row (not an object, no ``card_id``, a non-integer ``page``)
    is skipped on its own rather than discarding every card's shas; when
    ``problems`` is given, one line naming the row is appended to it so the
    caller can report the culprit.
    """
    rows = pages_cleaned.get("pages", [])  # type: ignore[union-attr]
    if not isinstance(rows, list):
        if problems is not None:
            problems.append(f"'pages' is {type(rows).__name__}, not a list")
        return {}
    out: dict[str, dict[int, str]] = {}
    for index, row in enumerate(rows):
        reason = _malformed(row)
        if reason is not None:
            if problems is not None:
                problems.append(f"pages[{index}]: {reason}")
            continue
        sha = row.get("source_page_sha256")
        if not sha:
            continue
        out.setdefault(row["card_id"], {})[int(row["page"])] = sha
    return out


def _malformed(row: object) -> str | None:
    if not isinstance(row, Mapping):
        return f"row is {type(row).__name__}, not an object"
    card_id = row.get("card_id")
    if not isinstance(card_id, str) or not card_id:
        return "no card_id"
    page = row.get("page")
    if isinstance(page, bool) or not isinstance(page, (int, str)):
        return f"{card_id}: page {page!r} is not an integer"
    try:
        int(page)
    except ValueError:
        return f"{card_id}: page {page!r} is not an integer"
    sha = row.get("source_page_sha256")
    if sha is not None and not isinstance(sha, str):
        return f"{card_id} page {page}: source_page_sha256 is not a string"
    return None


def is_stale(
    expected_digest: str | None,
    page_count: int,
    shas: Mapping[int, str],
) -> bool:
    """True iff ``shas`` no longer reproduce ``expected_digest``.

    ``expected_digest`` of ``None`` (the bundle card carries no digest
    field) or an incomplete ``shas`` (fewer entries than ``page_count``)
    means the check cannot run: unverifiable, not stale.
    """
    if expected_digest is None or len(shas) != page_count:
        return False
    return judged_pages_digest(shas.items()) != expected_digest
