"""Data shapes for scraped cards and the manifest.

Schema matches the war.gov ``uap-csv.csv`` columns 1:1, with normalization
applied at parse time. Field names are snake_case versions of the CSV columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

AssetType = Literal["PDF", "VID", "IMG", "AUD"]


class CardMetadata(BaseModel):
    """Single PURSUE entry as represented in the source CSV."""

    model_config = ConfigDict(extra="forbid")

    # Stable identity (derived)
    card_id: str = Field(..., description="sha256(asset_url || title)[:16]")

    # Core CSV fields
    title: str
    asset_type: AssetType = Field(..., description="Normalized: PDF | VID | IMG | AUD")
    agency: str
    release_date: str | None = None
    incident_date: str | None = None
    incident_location: str | None = None
    redacted: bool = False
    description: str | None = None

    # Asset locations
    asset_url: HttpUrl | None = None
    asset_filename: str | None = None
    modal_image_url: HttpUrl | None = None

    # DVIDS-hosted media (video + audio per Sprint 4f). Field name
    # retained as ``dvids_video_id`` for backwards-compat with prior
    # manifests + the upstream CSV column "DVIDS Video ID" — but the
    # value now also carries DVIDS audio IDs for AUD cards. The
    # value space is shared (DVIDS IDs are content-type-agnostic on
    # their end); only the embed path differs (/video/embed/<id> vs
    # /audio/embed/<id>). Read sites should gate on ``asset_type``,
    # not on field-name semantics.
    dvids_video_id: str | None = None
    video_title: str | None = None

    # Cross-references between entries (free-text in CSV; we keep verbatim)
    pdf_pairing: str | None = None
    video_pairing: str | None = None

    # Accessibility / DoD provenance (added upstream 2026-05-14 in tranche
    # c9cc83fcaf43 — alt-text per Section 508, VIRIN per DoDI 5040.02).
    image_alt_text: str | None = None
    image_virin: str | None = None

    # Original document classification extracted from upstream alt-text
    # when an explicit level is present. Set on parse; not a CSV column.
    # Values: "Top Secret" | "Secret" | "Confidential" | "Restricted" |
    # "Unclassified" — or None when upstream didn't say (most cards).
    original_classification: str | None = None

    # Curated display-date overlay (operator-approved per
    # .paircoder/plans/display-date-curation.md). Applied AFTER CSV
    # parsing by ``merge_display_dates``. The upstream CSV's
    # incident_date is preserved separately in manifest_incident_date_raw
    # so the audit trail survives the merge.
    display_date: str | None = None
    display_date_range: tuple[str, str] | None = None
    display_date_evidence: str | None = None
    display_date_evidence_card_ref: str | None = None
    display_date_curator: str | None = None
    display_date_approved_at: str | None = None
    display_date_abstention: str | None = None
    manifest_incident_date_raw: str | None = None

    # Anything we captured but didn't model — forward compat for future CSV cols
    raw: dict[str, Any] = Field(default_factory=dict)


class Manifest(BaseModel):
    """A complete snapshot of the index for a given fetch."""

    model_config = ConfigDict(extra="forbid")

    source_url: HttpUrl
    fetched_at: datetime
    csv_sha256: str = Field(..., description="Hash of the raw CSV bytes")
    cards: list[CardMetadata]

    @property
    def card_count(self) -> int:
        return len(self.cards)

    def diff(self, other: "Manifest") -> "ManifestDiff":
        """Return cards in self that are not in other (by card_id)."""
        other_ids = {c.card_id for c in other.cards}
        added = [c for c in self.cards if c.card_id not in other_ids]
        self_ids = {c.card_id for c in self.cards}
        removed = [c for c in other.cards if c.card_id not in self_ids]
        return ManifestDiff(added=added, removed=removed)


class ManifestDiff(BaseModel):
    added: list[CardMetadata]
    removed: list[CardMetadata]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)
