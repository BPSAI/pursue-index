"""Fail-closed eligibility of a tranche receipt for the autopilot.

A tranche is eligible only when its receipt
(``data/tranche-diffs/tranche-diff-<sha12>.json``) shows nothing but
field-level edits on cards that already exist, and every edited field is on
:data:`ALLOWED_FIELDS`. Anything else refuses:

* content work -- a new, renamed, re-saved, quarantined or restored card, or
  a row added to an existing card -- needs the attended release
  (:attr:`ExitCode.NEEDS_LEASE`, 20);
* everything else that is not an allowlisted field edit -- a removed card, a
  removed row, a field outside the allowlist, a summary bucket this code does
  not know -- is ineligible (:attr:`ExitCode.INELIGIBLE`, 21).

Precedence: when a receipt has both, 20 wins. Content work always needs the
attended release, and that release reviews the whole receipt anyway, so it
is the more useful answer; the 21 reasons are still listed.

A receipt that cannot be trusted to answer -- wrong tranche, missing summary
bucket, counts that disagree with the listed rows -- raises
:class:`ReceiptError` (40): regenerate it rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pursue_index.scrape.types import CardMetadata
from pursue_index.tranche_autopilot.outcome import ExitCode

__all__ = [
    "ALLOWED_FIELDS",
    "EXCLUDED_FIELDS",
    "HEAVY_BUCKETS",
    "REQUIRED_BUCKETS",
    "Eligibility",
    "ReceiptError",
    "assess",
]

# Manifest card fields (``scrape.types.CardMetadata``) whose edit changes
# only what the site says about a card, never which bytes it serves:
# upstream display text, dates, agency and location, pairing cross-references,
# accessibility text and the curated display-date overlay.
ALLOWED_FIELDS: frozenset[str] = frozenset({
    "title",
    "video_title",
    "description",
    "agency",
    "release_date",
    "incident_date",
    "incident_location",
    "featured",
    "pdf_pairing",
    "video_pairing",
    "image_alt_text",
    "image_virin",
    "original_classification",
    "display_date",
    "display_date_range",
    "display_date_evidence",
    "display_date_evidence_card_ref",
    "display_date_curator",
    "display_date_approved_at",
    "display_date_abstention",
    "manifest_incident_date_raw",
})

# Card fields that are NOT allowlisted, and why: identity (card_id), what the
# card serves or where the bytes come from (asset_*, modal_image_url,
# dvids_video_id), a redaction flag that signals the document itself changed
# (redacted), and the unmodelled passthrough (raw). Any field in neither set
# -- including any future *sha* or *size* field -- is refused as unknown.
EXCLUDED_FIELDS: frozenset[str] = frozenset({
    "card_id",
    "asset_type",
    "asset_url",
    "asset_filename",
    "modal_image_url",
    "dvids_video_id",
    "redacted",
    "raw",
})

HEAVY_BUCKETS: tuple[str, ...] = (
    "new_content",
    "renames_confirmed",
    "renames_metadata_only",
    "quarantined",
    "restored_unchanged",
    "restored_modified",
    "restored_unknown",
)
# Must be present in every receipt the autopilot reads; a receipt written
# before one of these existed cannot prove that bucket was empty.
REQUIRED_BUCKETS: tuple[str, ...] = (
    "new_content", "renames_confirmed", "quarantined", "restored_unchanged",
    "restored_modified", "restored_unknown", "removed", "field_only_changes",
    "row_changes",
)
_FIELD_BUCKET = "field_only_changes"
_ROW_BUCKET = "row_changes"


class ReceiptError(ValueError):
    """The receipt is not a trustworthy answer for this tranche."""


@dataclass
class Eligibility:
    verdict: str  # "eligible" | "needs-lease" | "ineligible"
    code: ExitCode | None
    reasons: list[str] = field(default_factory=list)
    fields_changed: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    field_change_cards: int = 0


def _checked_summary(receipt: dict[str, Any], tranche_sha: str) -> dict[str, int]:
    if receipt.get("tranche_sha256") != tranche_sha:
        raise ReceiptError("receipt tranche_sha256 does not match --tranche")
    summary = receipt.get("summary")
    if not isinstance(summary, dict):
        raise ReceiptError("receipt has no summary object")
    missing = [b for b in REQUIRED_BUCKETS if b not in summary]
    if missing:
        raise ReceiptError(f"receipt summary lacks bucket(s): {', '.join(missing)}")
    for name, count in summary.items():
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ReceiptError(f"summary bucket {name} is not a non-negative integer")
        rows = receipt.get(name)
        listed = len(rows) if isinstance(rows, list) else None
        if (listed is None and count) or (listed is not None and listed != count):
            raise ReceiptError(f"summary bucket {name}={count} disagrees with its rows")
    return dict(summary)


def _row_change_sides(receipt: dict[str, Any]) -> set[str]:
    sides: set[str] = set()
    for entry in receipt.get(_ROW_BUCKET) or []:
        rows = entry.get("rows") if isinstance(entry, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ReceiptError("row_changes entry has no rows list")
        sides |= {r.get("side") if isinstance(r, dict) else None for r in rows}
    return sides


def _changed_fields(receipt: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for entry in receipt.get(_FIELD_BUCKET) or []:
        diffs = entry.get("diffs") if isinstance(entry, dict) else None
        if not isinstance(diffs, list) or not diffs:
            raise ReceiptError("field_only_changes entry has no diffs list")
        for diff in diffs:
            name = diff.get("field") if isinstance(diff, dict) else None
            if not isinstance(name, str):
                raise ReceiptError("field_only_changes diff has no field name")
            names.add(name)
    return sorted(names)


def _content_reasons(summary: dict[str, int], sides: set[str]) -> list[str]:
    reasons = [f"{b}={summary[b]}" for b in HEAVY_BUCKETS if summary.get(b)]
    if "added" in sides:
        reasons.append("row_changes adds a row to an existing card")
    return reasons


def _ineligible_reasons(summary: dict[str, int], sides: set[str], fields: list[str]) -> list[str]:
    known = set(HEAVY_BUCKETS) | {_FIELD_BUCKET, _ROW_BUCKET}
    reasons = [f"{b}={n}" for b, n in sorted(summary.items()) if n and b not in known]
    if sides - {"added"}:
        reasons.append("row_changes removes or alters a row of an existing card")
    reasons += [f"field not on the metadata allowlist: {f}" for f in fields
                if f not in ALLOWED_FIELDS]
    return reasons


def assess(receipt: dict[str, Any], tranche_sha: str) -> Eligibility:
    """Classify ``receipt`` for ``tranche_sha``; raises :class:`ReceiptError`."""
    summary = _checked_summary(receipt, tranche_sha)
    sides = _row_change_sides(receipt)
    fields = _changed_fields(receipt)
    heavy = _content_reasons(summary, sides)
    other = _ineligible_reasons(summary, sides, fields)
    base = {"fields_changed": fields, "summary": summary,
            "field_change_cards": summary[_FIELD_BUCKET]}
    if heavy:
        return Eligibility("needs-lease", ExitCode.NEEDS_LEASE, heavy + other, **base)
    if other:
        return Eligibility("ineligible", ExitCode.INELIGIBLE, other, **base)
    return Eligibility("eligible", None, ["only allowlisted field edits"], **base)


def schema_fields() -> frozenset[str]:
    """Every manifest card field, for the allowlist completeness test."""
    return frozenset(CardMetadata.model_fields)
