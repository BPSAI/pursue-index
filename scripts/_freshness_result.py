"""The freshness gate's result: card classes, the failure ceilings and the release record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

RECORD_SCHEMA = "pursue-ocr-input-freshness/v1"
# A published PDF card with no registry row this many days after its release date is
# ``unregistered-stale``: longer than the daily archive's normal lag.
UNREGISTERED_STALE_DAYS = 3


@dataclass
class Result:
    stale: list[str] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    unregistered: list[str] = field(default_factory=list)
    unverifiable: list[tuple[str, str]] = field(default_factory=list)
    unregistered_stale: list[tuple[str, date]] = field(default_factory=list)
    unregistered_undated: list[str] = field(default_factory=list)
    checked: int = 0

    max_unverifiable: int | None = None
    max_unregistered_stale: int | None = None
    unregistered_days: int = UNREGISTERED_STALE_DAYS

    @property
    def over_ceiling(self) -> bool:
        return self.max_unverifiable is not None and len(self.unverifiable) > self.max_unverifiable

    @property
    def over_stale_ceiling(self) -> bool:
        return (
            self.max_unregistered_stale is not None
            and len(self.unregistered_stale) + len(self.unregistered_undated)
            > self.max_unregistered_stale
        )

    @property
    def failed(self) -> bool:
        return bool(self.stale) or self.over_ceiling or self.over_stale_ceiling

    def record(self) -> dict:
        """Deterministic release record (no timestamps, so a rerun is byte-stable)."""
        return {
            "schema": RECORD_SCHEMA,
            "checked": self.checked,
            "stale": len(self.stale),
            "covered": len(self.covered),
            "unregistered_pdf_cards": {
                "count": len(self.unregistered), "cards": sorted(self.unregistered),
            },
            "unregistered_stale_pdf_cards": {
                "count": len(self.unregistered_stale),
                "cards": sorted(c for c, _ in self.unregistered_stale),
                "days": self.unregistered_days,
            },
            "unregistered_undated_pdf_cards": {
                "count": len(self.unregistered_undated),
                "cards": sorted(self.unregistered_undated),
            },
            "unverifiable_provenance": {
                "count": len(self.unverifiable),
                "cards": [{"card_id": c, "reason": r} for c, r in self.unverifiable],
            },
        }
