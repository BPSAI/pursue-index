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

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, ClassVar

from pursue_index.text_control import strip_control_chars

__all__ = [
    "NO_PRIOR_RELEASE_DISCLAIMER",
    "POSITIVE_TIERS",
    "DateBasis",
    "NoPriorReleaseFound",
    "ProvenanceClaim",
    "ProvenanceResult",
    "ProvenanceTier",
    "from_dict",
    "is_citable_prior_source",
    "require_web_url",
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
    """How an establishing date was derived — the bases are never conflated.

    A Wayback first-capture timestamp, a sitemap ``<lastmod>``, an HTTP
    ``Last-Modified`` header, a publisher-stated date and a PDF's internal
    ``CreationDate`` are evidence of very different strength; the consumer must
    always know which one it holds.

    ``SITEMAP_LASTMOD`` and ``HTTP_LAST_MODIFIED`` are close cousins — neither
    is a publication date — but they are separate members because they arrive
    from different places and are written in different syntaxes: a sitemap
    ``<lastmod>`` element is ISO 8601, a ``Last-Modified`` response header is
    the RFC 7231 date syntax. A record that names one of them is stating where
    its value came from, so it is also stating how the value reads.
    """

    WAYBACK_FIRST_CAPTURE = "wayback_first_capture"
    SITEMAP_LASTMOD = "sitemap_lastmod"
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


def require_web_url(value: object, field: str) -> None:
    """Require an absolute http(s) URL — the only kind a reader can follow.

    These records exist to become citations on a public page, and the value is
    copied verbatim from third-party sitemap ``<loc>`` text or stored JSON, so
    it arrives as whatever that source held. Two things make a value usable: it
    has to be text at all, and it has to name a web address. Both are settled
    here, at construction — the one place every path into a record goes through.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string URL, got {type(value).__name__}")
    if not value.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError(
            f"{field} must use an http:// or https:// scheme, got {value!r}"
        )


#: A ``scheme:`` prefix and everything after it. The scheme grammar is RFC 3986's:
#: a letter, then letters, digits and ``+ - .``.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:(.*)$", re.DOTALL)


def _uri_payload(text: str) -> str | None:
    """The part after a ``scheme:`` prefix, or ``None`` when there is no scheme.

    A colon is ordinary punctuation in prose, and the tokens these rules capture
    are prose: ``Time:`` and ``Time: The Weekly Magazine`` are an outlet name
    with a clause's colon attached, not a URI in a ``time`` scheme. A colon
    introduces a scheme only when what follows is URI-shaped — a ``//``
    authority, or a payload that begins immediately with a non-space character.
    """
    match = _SCHEME_RE.match(text)
    if match is None:
        return None
    payload = match.group(1)
    if payload.startswith("//") or (payload and not payload[0].isspace()):
        return payload
    return None


def is_citable_prior_source(value: str) -> bool:
    """True when ``value`` is something a reader can follow, as written.

    A prior source is read out of CSV prose and published as the pointer a
    reader is given, so three shapes qualify and are kept verbatim: a plain
    outlet name ("COMETA report", "Time:"), a bare domain ("dvidshub.net"), and
    an absolute http(s) URL.

    Three shapes name no address a reader could follow, so they never become
    one:

    * A URI in another scheme — ``data:``, ``file:``, ``javascript:``. Only
      http(s) is an address a reader has any way to open.
    * A protocol-relative ``//host/path``. It states a host but leaves the
      scheme to whatever renders it, so the value itself is not the address; a
      citation writes the address out in full.
    * A value that is only URI-shaped once characters with no text of their own
      are removed. Those characters are removed *before* the value is read, so a
      scheme split across a tab is recognised as the scheme it names — but a URL
      a reader can follow is the exact characters they would type, so a value
      that needs the removal to become one is not that URL.
    """
    text = value.strip()
    normalized = strip_control_chars(text).strip()
    if normalized.startswith("//"):
        return False
    if _uri_payload(normalized) is None:
        return True
    if normalized != text:
        return False
    return normalized.lower().startswith(_ALLOWED_URL_SCHEMES)


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
        require_web_url(self.artifact_url, "artifact_url")
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
