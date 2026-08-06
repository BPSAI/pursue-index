"""Tiered, dated provenance claims (spec §5).

Every later stage of the pipeline writes its provenance finding into this
model. Its whole job is to make one specific untruth *unrepresentable*: the
claim that a document was **not** previously released.

Absence of a prior release can never be proven by a search that did not find
one — a capture we did not look at, an archive we do not have, a mirror behind
a login all leave the negative unestablished. So the model offers no boolean
``is_novel`` flag and no tier meaning "novel" / "not previously released".

Instead there are two shapes:

* :class:`ProvenanceClaim` — a *positive* assertion that a release (or its
  content) appeared before the release under examination. It is only
  constructible with the evidence that backs it: what was searched
  (``identifier``), where the prior copy lives (``source`` + ``artifact_url``),
  when it was established (``established_date``) and on what footing that date
  rests (``date_basis``). None of these silently default.
* :class:`NoPriorReleaseFound` — the honest negative. It records only what was
  searched and states, in words, that *absence of a prior release is not
  established*.

Pure dataclasses and (de)serialisation. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, ClassVar

__all__ = [
    "NO_PRIOR_RELEASE_DISCLAIMER",
    "POSITIVE_TIERS",
    "DateBasis",
    "NoPriorReleaseFound",
    "ProvenanceClaim",
    "ProvenanceResult",
    "ProvenanceTier",
    "from_dict",
]


class ProvenanceTier(StrEnum):
    """The four §5 outcomes of a prior-release search.

    The first three are *positive* — a prior release was found, and the tier
    says how much of it. The fourth, :attr:`NO_PRIOR_RELEASE_FOUND`, is not a
    claim of novelty; it is the record that a search returned nothing, and it
    belongs to :class:`NoPriorReleaseFound`, never to a :class:`ProvenanceClaim`.
    """

    PREVIOUSLY_RELEASED = "previously_released"
    PREVIOUSLY_RELEASED_IN_PART = "previously_released_in_part"
    CONTENT_PREVIOUSLY_PUBLISHED = "content_previously_published"
    NO_PRIOR_RELEASE_FOUND = "no_prior_release_found"


#: The tiers a positive :class:`ProvenanceClaim` may assert.
POSITIVE_TIERS: frozenset[ProvenanceTier] = frozenset(
    {
        ProvenanceTier.PREVIOUSLY_RELEASED,
        ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
        ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
    }
)


class DateBasis(StrEnum):
    """How an establishing date was derived — the four are never conflated.

    A Wayback first-capture timestamp, an HTTP ``Last-Modified`` header, a
    publisher-stated date and a PDF's internal ``CreationDate`` are evidence of
    very different strength; the consumer must always know which one it holds.
    """

    WAYBACK_FIRST_CAPTURE = "wayback_first_capture"
    HTTP_LAST_MODIFIED = "http_last_modified"
    PUBLISHER_DATE = "publisher_date"
    PDF_CREATION_DATE = "pdf_creation_date"


#: The wording every ``no_prior_release_found`` record serialises with.
NO_PRIOR_RELEASE_DISCLAIMER = "absence of a prior release is not established"

_CLAIM_KIND = "provenance_claim"
_NEGATIVE_KIND = "no_prior_release_found"


def _require_text(value: object, field_name: str, message: str) -> None:
    """Raise ``ValueError(message)`` unless ``value`` is non-blank text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)



_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _require_web_url(value: str, field: str) -> None:
    """Reject any artifact URL that is not plain http(s).

    These records exist to become citations on a public page, and
    ``artifact_url`` is populated verbatim from third-party sitemap ``<loc>``
    values. A ``javascript:`` or ``data:`` URL that only had to be non-blank
    would survive into the published artifact — a stored-XSS / malicious-link
    vector queued for the moment anything renders it. Validate at construction,
    which is the one place every path goes through.
    """
    if not value.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError(
            f"{field} must use an http:// or https:// scheme, got {value!r}"
        )

@dataclass(frozen=True)
class ProvenanceClaim:
    """A dated, sourced assertion that a release (or its content) is not new.

    Constructing one without a source URL, an establishing date or a
    ``date_basis`` raises — an undated or unsourced provenance claim is
    unsupportable, so the model refuses to hold one.
    """

    tier: ProvenanceTier
    identifier: str
    source: str
    artifact_url: str
    established_date: date
    date_basis: DateBasis

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ProvenanceTier):
            raise TypeError(f"tier must be a ProvenanceTier, got {self.tier!r}")
        if self.tier not in POSITIVE_TIERS:
            raise ValueError(
                f"a positive claim cannot use tier {self.tier.value!r}; "
                "'no_prior_release_found' is recorded by NoPriorReleaseFound"
            )
        _require_text(self.identifier, "identifier", "a claim requires the identifier searched")
        _require_text(self.source, "source", "a claim requires a source that was searched")
        _require_text(
            self.artifact_url, "artifact_url", "a provenance claim requires a source artifact URL"
        )
        _require_web_url(self.artifact_url, "artifact_url")
        if not isinstance(self.established_date, date):
            raise TypeError("a provenance claim requires an establishing date; none was given")
        if not isinstance(self.date_basis, DateBasis):
            raise TypeError("a provenance claim requires a date_basis; none was given")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": _CLAIM_KIND,
            "tier": self.tier.value,
            "identifier": self.identifier,
            "source": self.source,
            "artifact_url": self.artifact_url,
            "established_date": self.established_date.isoformat(),
            "date_basis": self.date_basis.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceClaim:
        return cls(
            tier=ProvenanceTier(data["tier"]),
            identifier=data["identifier"],
            source=data["source"],
            artifact_url=data["artifact_url"],
            established_date=date.fromisoformat(data["established_date"]),
            date_basis=DateBasis(data["date_basis"]),
        )


@dataclass(frozen=True)
class NoPriorReleaseFound:
    """The honest negative: a search found no prior release.

    This is *not* a claim of novelty. It carries only what was searched and the
    standing disclaimer that :data:`NO_PRIOR_RELEASE_DISCLAIMER` — absence of a
    prior release is not established.
    """

    identifier: str
    sources_searched: tuple[str, ...]
    searched_date: date | None = None

    tier: ClassVar[ProvenanceTier] = ProvenanceTier.NO_PRIOR_RELEASE_FOUND
    disclaimer: ClassVar[str] = NO_PRIOR_RELEASE_DISCLAIMER

    def __post_init__(self) -> None:
        _require_text(
            self.identifier, "identifier", "a no-prior-release record requires the identifier searched"
        )
        if not self.sources_searched:
            raise ValueError("a no-prior-release record requires at least one source searched")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": _NEGATIVE_KIND,
            "tier": self.tier.value,
            "identifier": self.identifier,
            "sources_searched": list(self.sources_searched),
            "searched_date": self.searched_date.isoformat() if self.searched_date else None,
            "disclaimer": NO_PRIOR_RELEASE_DISCLAIMER,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoPriorReleaseFound:
        raw_date = data.get("searched_date")
        return cls(
            identifier=data["identifier"],
            sources_searched=tuple(data["sources_searched"]),
            searched_date=date.fromisoformat(raw_date) if raw_date else None,
        )


ProvenanceResult = ProvenanceClaim | NoPriorReleaseFound


def from_dict(data: dict[str, Any]) -> ProvenanceResult:
    """Rebuild a claim or negative record from its serialised form."""
    kind = data.get("kind")
    if kind == _CLAIM_KIND:
        return ProvenanceClaim.from_dict(data)
    if kind == _NEGATIVE_KIND:
        return NoPriorReleaseFound.from_dict(data)
    raise ValueError(f"unknown provenance record kind: {kind!r}")
