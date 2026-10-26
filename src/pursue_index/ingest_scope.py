"""Full-tranche PDF/IMG worklist scope (R7C.1 / #168).

``summarize_ingest_work`` (``ingest_run.py``) only ever scoped a tranche-diff's
``new_content`` rows (Class B). Three classes of real work fall out of that:

  * quarantined-new cards (Class C) that clear the approval gate as new cards
    with no explicit per-card approval marker -- today ``ingest approve``
    either turns a quarantined row into a rename alias or leaves it
    "not addressed"; an unaddressed row still ships as a new card.
  * the new side of an approved rename, whose card_id has no OCR sidecar yet
    (sidecars, the QC bundle and ``qc-coverage`` are keyed by card_id).
  * existing cards whose current registry byte sha no longer matches what
    their OCR sidecar's ``meta.json`` recorded (upstream silently replaced
    the bytes behind an already-ingested card).

``scope_pdf_img_cards`` computes the union of all four classes for a single
tranche, tagging each card_id with which class put it there. It never
touches VID/AUD content -- those stay on the existing A/V worklist path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.card_id import InvalidCardIdError, require_card_id
from pursue_index.tranche_resave import RESAVE_BUCKET

REASON_NEW = "new"
REASON_QUARANTINED_NEW = "quarantined-new"
REASON_RENAMED = "renamed"
REASON_BYTES_CHANGED = "bytes-changed"

# Real tranche-diffs never carry `asset_type` on new_content/quarantined
# rows (verified against every diff on disk as of Release 7) -- the
# filename extension is the fallback signal. VID/AUD belong to the
# separate A/V worklist, not this one.
_AV_ASSET_TYPES = {"VID", "AUD"}
_AV_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mp3", ".wav", ".m4a"}


@dataclass(frozen=True)
class ScopedCard:
    card_id: str
    reason: str


def _is_pdf_img_asset(
    filename: str | None, url: str | None, asset_type: str | None
) -> bool:
    if asset_type:
        return asset_type not in _AV_ASSET_TYPES
    name = filename or url or ""
    if not name:
        return False
    return Path(name).suffix.lower() not in _AV_EXTENSIONS


def _has_new_side_pdf_img(row: dict[str, Any]) -> bool:
    return _is_pdf_img_asset(
        row.get("new_asset_filename"), row.get("new_asset_url"), row.get("asset_type")
    )


def _auto_rename_rows(diff: dict[str, Any]) -> list[dict[str, Any]]:
    """Renames the tranche approval accepts without a per-card flag."""
    return [row for key in ("renames_confirmed", RESAVE_BUCKET)
            for row in diff.get(key, []) or []]


def scope_pdf_img_cards(
    diff: dict[str, Any],
    tranche_sha: str,
    *,
    aliases: list[dict[str, Any]] | None = None,
    registry_sha_by_card: dict[str, str] | None = None,
    ocr_meta_sha_by_card: dict[str, str] | None = None,
) -> list[ScopedCard]:
    """Every PDF/IMG card_id this tranche must (re)download/OCR/embed.

    Scope, in order (first-seen wins; a card is tagged once):

      1. ``new`` -- diff's ``new_content`` rows with a PDF/IMG asset.
      2. ``quarantined-new`` -- diff's ``quarantined`` rows with a PDF/IMG
         asset that this tranche did NOT resolve into a rename.
      3. ``renamed`` -- ``aliases`` rows established for this tranche
         (``tranche_sha256 == tranche_sha``) whose new side has a PDF/IMG
         asset (looked up from the matching ``quarantined`` row).
         Confirmed (Class A) renames in the diff's ``renames_confirmed`` and
         byte-evidenced re-saves in its ``renames_metadata_only`` are scoped
         the same way, from their own row, since the tranche approval
         accepts them without a per-card flag.
      4. ``bytes-changed`` -- any card_id in ``registry_sha_by_card`` whose
         current byte sha differs from the one recorded in
         ``ocr_meta_sha_by_card`` (i.e. it was OCR'd before, under
         different bytes).

    ``aliases``/``registry_sha_by_card``/``ocr_meta_sha_by_card`` default to
    empty -- a bare diff scopes only Class B.
    """
    aliases = aliases or []
    registry_sha_by_card = registry_sha_by_card or {}
    ocr_meta_sha_by_card = ocr_meta_sha_by_card or {}

    out: list[ScopedCard] = []
    seen: set[str] = set()

    def _add(card_id: str, reason: str) -> None:
        require_card_id(card_id)
        if card_id in seen:
            return
        seen.add(card_id)
        out.append(ScopedCard(card_id, reason))

    for row in diff.get("new_content", []) or []:
        if _is_pdf_img_asset(
            row.get("asset_filename"), row.get("asset_url"), row.get("asset_type")
        ):
            _add(row["new_card_id"], REASON_NEW)

    quarantined_by_new_id: dict[str, dict[str, Any]] = {
        row["new_card_id"]: row for row in (diff.get("quarantined", []) or [])
    }
    renamed_this_tranche = {
        row["new_card_id"] for row in aliases if row.get("tranche_sha256") == tranche_sha
    }

    for new_card_id, row in quarantined_by_new_id.items():
        if new_card_id in renamed_this_tranche:
            continue
        if _has_new_side_pdf_img(row):
            _add(new_card_id, REASON_QUARANTINED_NEW)

    for new_card_id in renamed_this_tranche:
        row = quarantined_by_new_id.get(new_card_id)
        if row is None:
            continue
        if _has_new_side_pdf_img(row):
            _add(new_card_id, REASON_RENAMED)

    for row in _auto_rename_rows(diff):
        if _has_new_side_pdf_img(row):
            _add(row["new_card_id"], REASON_RENAMED)

    for card_id, current_sha in registry_sha_by_card.items():
        recorded_sha = ocr_meta_sha_by_card.get(card_id)
        if recorded_sha and recorded_sha != current_sha:
            _add(card_id, REASON_BYTES_CHANGED)

    return out


def load_aliases(aliases_path: Path) -> list[dict[str, Any]]:
    """Rows from ``data/card-aliases.json``'s ``aliases`` list, or ``[]``."""
    if not aliases_path.exists():
        return []
    payload = json.loads(aliases_path.read_text(encoding="utf-8"))
    rows = payload.get("aliases", []) if isinstance(payload, dict) else payload
    return list(rows)


def load_registry_sha_map(registry_path: Path) -> dict[str, str]:
    """``card_id -> byte_sha256`` from the append-only registry (last row wins)."""
    out: dict[str, str] = {}
    if not registry_path.exists():
        return out
    for lineno, line in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        card_id = row.get("card_id")
        sha = row.get("byte_sha256")
        if card_id and sha:
            try:
                require_card_id(card_id)
            except InvalidCardIdError as exc:
                raise InvalidCardIdError(f"{registry_path}:{lineno}: {exc}") from exc
            out[card_id] = sha
    return out


def load_ocr_meta_sha_map(ocr_dir: Path, card_ids: Iterable[str]) -> dict[str, str]:
    """``card_id -> pdf_sha256`` for every candidate card_id with an OCR sidecar."""
    out: dict[str, str] = {}
    for card_id in card_ids:
        require_card_id(card_id)
        meta_path = ocr_dir / card_id / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sha = meta.get("pdf_sha256")
        if sha:
            out[card_id] = sha
    return out


def scope_worklist(
    diff: dict[str, Any],
    tranche_sha: str,
    *,
    aliases_path: Path,
    registry_path: Path,
    ocr_dir: Path,
) -> list[ScopedCard]:
    """``scope_pdf_img_cards`` wired to the on-disk aliases/registry/OCR state."""
    aliases = load_aliases(aliases_path)
    registry_sha = load_registry_sha_map(registry_path)
    ocr_meta_sha = load_ocr_meta_sha_map(ocr_dir, registry_sha.keys())
    return scope_pdf_img_cards(
        diff,
        tranche_sha,
        aliases=aliases,
        registry_sha_by_card=registry_sha,
        ocr_meta_sha_by_card=ocr_meta_sha,
    )
