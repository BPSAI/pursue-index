"""Era vocabulary and the 2015+ negative record (spec §4a/§5, PV1.3).

The types the bucketing stage produces. :class:`Era` is the five-way §4a
taxonomy; :class:`CardEra` is one card's era+agency assignment with the date it
was read from; :class:`EraNoPriorRelease` is the ``no_prior_release_found``
record a 2015+ card receives — reusing PV1.1's tier and disclaimer but resting
on the document's *era* rather than a search of external sources.

Pure dataclasses + labels; no I/O. Kept apart from
:mod:`pursue_index.era_bucketing` so both stay small and single-purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from pursue_index.provenance import NO_PRIOR_RELEASE_DISCLAIMER, ProvenanceTier

__all__ = [
    "DOCUMENT_DATE_FIELDS",
    "ERA_LABELS",
    "ERA_RATIONALE",
    "MODERN_MIN_YEAR",
    "CardEra",
    "Era",
    "EraNoPriorRelease",
    "era_for_year",
    "era_rationale",
]

#: The era rationale recorded on every 2015+ negative (spec §4a).
ERA_RATIONALE = "A record cannot appear in an archive assembled before it existed."

#: Cards in this era or later carry a ``no_prior_release_found`` record.
MODERN_MIN_YEAR = 2015

#: Fields that carry a document era (``release_date`` deliberately excluded — it
#: is the war.gov publication date, ≈2026 for every card, not a document era).
DOCUMENT_DATE_FIELDS = ("display_date", "incident_date")


class Era(StrEnum):
    """The five §4a era buckets. Values are stable slugs used in the artifact."""

    MODERN_OPERATIONAL = "2015_plus"
    ERA_1990_2014 = "1990_2014"
    ERA_1970_1989 = "1970_1989"
    PRE_1970 = "pre_1970"
    UNDATED = "undated"


#: Human labels for reporting; keyed by the enum's slug value.
ERA_LABELS: dict[Era, str] = {
    Era.MODERN_OPERATIONAL: "2015+ (modern operational)",
    Era.ERA_1990_2014: "1990-2014",
    Era.ERA_1970_1989: "1970-1989",
    Era.PRE_1970: "pre-1970 (historical)",
    Era.UNDATED: "undated",
}


def era_for_year(year: int) -> Era:
    """Bucket a defensible document-era ``year`` into its §4a era."""
    if year >= MODERN_MIN_YEAR:
        return Era.MODERN_OPERATIONAL
    if year >= 1990:
        return Era.ERA_1990_2014
    if year >= 1970:
        return Era.ERA_1970_1989
    return Era.PRE_1970


def era_rationale(year: int, source: str) -> str:
    """The per-card rationale: era reasoning (§4a) + the §5 disclaimer verbatim."""
    disclaimer = NO_PRIOR_RELEASE_DISCLAIMER[0].upper() + NO_PRIOR_RELEASE_DISCLAIMER[1:]
    return (
        f"This document is dated {year} ({ERA_LABELS[Era.MODERN_OPERATIONAL]}), "
        f"established via the manifest '{source}' field. {ERA_RATIONALE} A modern "
        f"operational record has no plausible prior-release surface. {disclaimer}."
    )


@dataclass(frozen=True)
class CardEra:
    """One card's era + agency assignment, with the date it was read from."""

    card_id: str
    identifier: str
    title: str
    agency: str
    era: Era
    year: int | None
    date_source: str | None
    raw_date: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "identifier": self.identifier,
            "title": self.title,
            "agency": self.agency,
            "era": self.era.value,
            "year": self.year,
            "date_source": self.date_source,
            "raw_date": self.raw_date,
        }


@dataclass(frozen=True)
class EraNoPriorRelease:
    """A ``no_prior_release_found`` record for a 2015+ card (spec §4a/§5).

    Its basis is the document's era, so it carries the establishing year, the
    manifest field that year was read from, and a ``rationale`` that states the
    era reasoning and the standing §5 disclaimer. It reuses PV1.1's
    ``NO_PRIOR_RELEASE_FOUND`` tier and disclaimer, but is *not* a claim of
    novelty — only 2015+ cards may hold one.
    """

    card_id: str
    identifier: str
    title: str
    agency: str
    established_year: int
    date_source: str
    established_date: str
    rationale: str

    era: ClassVar[Era] = Era.MODERN_OPERATIONAL
    tier: ClassVar[ProvenanceTier] = ProvenanceTier.NO_PRIOR_RELEASE_FOUND
    disclaimer: ClassVar[str] = NO_PRIOR_RELEASE_DISCLAIMER

    def __post_init__(self) -> None:
        for name in ("card_id", "identifier", "date_source", "rationale"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"an era no-prior-release record requires non-blank {name}")
        if not isinstance(self.established_year, int) or self.established_year < MODERN_MIN_YEAR:
            raise ValueError(
                "an era no-prior-release record is only for 2015+ cards; "
                f"got established_year={self.established_year!r}"
            )
        if self.date_source not in DOCUMENT_DATE_FIELDS:
            raise ValueError(
                f"era must rest on a document-date field {DOCUMENT_DATE_FIELDS}, "
                f"not {self.date_source!r} (release_date is not a document era)"
            )
        if NO_PRIOR_RELEASE_DISCLAIMER not in self.rationale.lower():
            raise ValueError("the rationale must carry the spec §5 disclaimer verbatim")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "era_no_prior_release",
            "tier": self.tier.value,
            "era": self.era.value,
            "card_id": self.card_id,
            "identifier": self.identifier,
            "title": self.title,
            "agency": self.agency,
            "established_year": self.established_year,
            "date_source": self.date_source,
            "established_date": self.established_date,
            "rationale": self.rationale,
            "disclaimer": NO_PRIOR_RELEASE_DISCLAIMER,
        }
