"""The typed claim the identifier resolver emits (spec §5, §6, PV1.5).

A :class:`ResolvedClaim` is the resolver's output: a *positive* provenance
assertion backed by a resolved artifact. It reuses PV1.1's
:class:`~pursue_index.provenance.ProvenanceTier` taxonomy and enforces, in its
constructor, the honesty rules the resolver must never violate:

* **Never the negative tier.** Absence of a prior release is not a claim; it is
  never a :class:`ResolvedClaim`.
* **A snippet is not an artifact.** A claim can never be built from a
  search-engine snippet (:attr:`ResolutionSource.SEARCH_SNIPPET`); it is
  refused at construction.
* **Strong claims are dated and sourced.** ``previously_released`` and
  ``previously_released_in_part`` require both a source artifact URL and a dated
  ``date_basis`` — an undated "this record was released" claim is unsupportable.
* **Content-published is a weaker, honest claim.**
  ``content_previously_published`` (the COMETA case, spec §6c) asserts only that
  the *content* is public, not that *this record* was released, so it may rest
  on a named prior publication rather than a fetchable artifact — and its date
  may be absent when the source gives only a year.
* **The page-image flag belongs to the partial tier.** The "compare page
  images later" flag is meaningful only for ``previously_released_in_part``.

Pure dataclass + (de)serialisation. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from pursue_index.provenance import POSITIVE_TIERS, DateBasis, ProvenanceTier, require_web_url

__all__ = [
    "ResolutionSource",
    "ResolvedClaim",
]

_STRONG_TIERS = frozenset(
    {ProvenanceTier.PREVIOUSLY_RELEASED, ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART}
)


class ResolutionSource(StrEnum):
    """Where a claim's artifact came from — a snippet is explicitly not one."""

    CATALOGUE = "catalogue"
    KNOWN_ARCHIVE = "known_archive"
    GOVERNMENT_DESCRIPTION = "government_description"
    SEARCH_SNIPPET = "search_snippet"


@dataclass(frozen=True)
class ResolvedClaim:
    """A dated-when-strong, sourced prior-release claim resolved from an artifact."""

    card_id: str
    tier: ProvenanceTier
    source: ResolutionSource
    identifier_kind: str = ""
    identifier_value: str = ""
    artifact_url: str = ""
    established_date: date | None = None
    date_basis: DateBasis | None = None
    prior_publication: str = ""
    needs_page_image_comparison: bool = False

    def __post_init__(self) -> None:
        self._check_tier_and_source()
        self._check_dates()
        self._check_evidence()

    def _check_tier_and_source(self) -> None:
        if not isinstance(self.tier, ProvenanceTier):
            raise TypeError(f"tier must be a ProvenanceTier, got {self.tier!r}")
        if self.tier not in POSITIVE_TIERS:
            raise ValueError(
                f"a resolved claim is a positive assertion; tier {self.tier.value!r} "
                "cannot be used ('no_prior_release_found' is not a resolver outcome)"
            )
        if not isinstance(self.source, ResolutionSource):
            raise TypeError(f"source must be a ResolutionSource, got {self.source!r}")
        if self.source is ResolutionSource.SEARCH_SNIPPET:
            raise ValueError("a claim is never built from a search-engine snippet")
        if not str(self.card_id).strip():
            raise ValueError("a resolved claim requires a card_id")

    def _check_dates(self) -> None:
        if (self.established_date is None) != (self.date_basis is None):
            raise ValueError("established_date and date_basis must be set together or not at all")
        if self.established_date is not None and not isinstance(self.established_date, date):
            raise TypeError("established_date must be a date")

    def _check_evidence(self) -> None:
        # Shared with ProvenanceClaim rather than re-implemented: this type is
        # the one the identifier resolver populates, with `artifact_url` taken
        # verbatim from a third-party sitemap <loc>, and it serialises into the
        # artifact intended to back public citations. Guarding only the sibling
        # class left this path wide open (caught on security re-audit).
        if self.artifact_url.strip():
            require_web_url(self.artifact_url, "artifact_url")
        if self.tier in _STRONG_TIERS:
            if not self.artifact_url.strip():
                raise ValueError(f"tier {self.tier.value!r} requires a source artifact URL")
            if self.established_date is None:
                raise ValueError(f"tier {self.tier.value!r} requires an establishing date")
        elif self.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED and not (
            self.artifact_url.strip() or self.prior_publication.strip()
        ):
            raise ValueError(
                "content_previously_published requires an artifact URL or a named prior publication"
            )
        if self.needs_page_image_comparison and self.tier is not ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART:
            raise ValueError(
                "the page-image-comparison flag belongs only to previously_released_in_part"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "resolved_claim",
            "card_id": self.card_id,
            "tier": self.tier.value,
            "source": self.source.value,
            "identifier_kind": self.identifier_kind,
            "identifier_value": self.identifier_value,
            "artifact_url": self.artifact_url,
            "established_date": self.established_date.isoformat() if self.established_date else None,
            "date_basis": self.date_basis.value if self.date_basis else None,
            "prior_publication": self.prior_publication,
            "needs_page_image_comparison": self.needs_page_image_comparison,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolvedClaim:
        raw_date = data.get("established_date")
        raw_basis = data.get("date_basis")
        return cls(
            card_id=data["card_id"],
            tier=ProvenanceTier(data["tier"]),
            source=ResolutionSource(data["source"]),
            identifier_kind=data.get("identifier_kind", ""),
            identifier_value=data.get("identifier_value", ""),
            artifact_url=data.get("artifact_url", ""),
            established_date=date.fromisoformat(raw_date) if raw_date else None,
            date_basis=DateBasis(raw_basis) if raw_basis else None,
            prior_publication=data.get("prior_publication", ""),
            needs_page_image_comparison=bool(data.get("needs_page_image_comparison", False)),
        )
