"""Data shapes for scraped cards and the manifest.

Schema matches the war.gov ``uap-csv.csv`` columns 1:1, with normalization
applied at parse time. Field names are snake_case versions of the CSV columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

AssetType = Literal["PDF", "VID", "IMG"]


class CardMetadata(BaseModel):
    """Single PURSUE entry as represented in the source CSV."""

    model_config = ConfigDict(extra="forbid")

    # Stable identity (derived)
    card_id: str = Field(..., description="sha256(asset_url || title)[:16]")

    # Core CSV fields
    title: str
    asset_type: AssetType = Field(..., description="Normalized: PDF | VID | IMG")
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

    # Video-specific
    dvids_video_id: str | None = None
    video_title: str | None = None

    # Cross-references between entries (free-text in CSV; we keep verbatim)
    pdf_pairing: str | None = None
    video_pairing: str | None = None

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
