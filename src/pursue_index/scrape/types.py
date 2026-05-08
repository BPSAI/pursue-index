"""Data shapes for scraped cards and the manifest.

Card metadata schema is intentionally permissive — fields are Optional where
we may not always be able to extract them from card or modal. The ``raw`` dict
preserves anything else we capture so downstream stages can recover.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CardMetadata(BaseModel):
    """Single PURSUE card as scraped from the index."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # Stable identity
    card_id: str = Field(..., description="Stable id, hashed from PDF URL if no native id")
    pdf_url: HttpUrl
    pdf_filename: str

    # Filterable fields shown on the index table
    agency: str | None = None
    release_date: str | None = None  # ISO date if parseable, else original string
    incident_date: str | None = None
    incident_location: str | None = None
    case_type: str | None = Field(default=None, alias="type")

    # Modal-only enrichments
    title: str | None = None
    description: str | None = None
    file_size_bytes: int | None = None
    page_count: int | None = None

    # Anything we captured but didn't model
    raw: dict[str, Any] = Field(default_factory=dict)


class Manifest(BaseModel):
    """A complete snapshot of the index for a given release/run."""

    model_config = ConfigDict(extra="forbid")

    release: str = Field(default="release_01", description="DOW release identifier")
    source_url: HttpUrl
    scraped_at: datetime
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
