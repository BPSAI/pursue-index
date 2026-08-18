"""Sitemap-derived source catalogue (spec §2 and §3, §7 step 3).

A local index of *candidate* prior-disclosure sources, enumerated from the four
sitemap indexes published via ``documents3.theblackvault.com/robots.txt`` (spec
§2b: 157,628 URLs, of which the UFO-relevant slice is ~8,000). One row per URL:
its filename, the sitemap's last-modified value and the basis that value rests
on, and an inferred agency and era.

**Index only.** Nothing here downloads a byte of the documents themselves. The
enumeration runs through :class:`~pursue_index.sitemap_fetch.CourteousFetcher`,
which fetches sitemaps only; the ``<loc>`` asset URLs are *recorded*, never
requested. Fetching those bytes is a later phase.

Three disciplines carry the doctrine:

* **The ``UFOFiles/`` tree is excluded — spec §2a.** That tree contains only
  mirrors of the PURSUE releases themselves (of 73 matched files, 73/73
  *postdate* their PURSUE release; zero precede it). Used as a "previously
  disclosed" reference it would report PURSUE's own material as previously
  disclosed and poison the candidate set. So :func:`is_ufofiles` drops it, and
  the count dropped is recorded in the artifact.
* **A last-modified value is never a publication date — spec §6d.** Those
  values cluster in a five-minute window on 2020-05-30; they date "existed on
  this host by", not publication. Every row states the basis its value rests on
  — ``sitemap_lastmod`` for the ``<lastmod>`` element these rows are built from
  — and the *era* is inferred from the path/filename instead, independently of
  the mtime.
* **Era is inferred, not asserted.** A four-digit year in the path yields an era
  bucket (reusing :func:`~pursue_index.era_models.era_for_year`); absent
  one, the row is ``undated``. This is a weak, best-effort hint for triage, not
  a provenance claim.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from pursue_index.era_dates import parse_year
from pursue_index.era_models import era_for_year
from pursue_index.provenance import DateBasis, require_web_url
from pursue_index.sitemap_fetch import (
    DEFAULT_ROBOTS_URL,
    CourteousFetcher,
    SitemapFetchError,
    UrlRow,
    is_listing_url,
    parse_robots_sitemaps,
    parse_sitemap_index,
    parse_url_entries,
)

__all__ = [
    "INVALID_URL_EXCLUSION_REASON",
    "OUTPUT_PATH",
    "UFOFILES_EXCLUSION_REASON",
    "Catalogue",
    "SourceEntry",
    "build_catalogue",
    "build_catalogue_from_fetcher",
    "build_output",
    "entries_from_rows",
    "entry_from_url",
    "infer_agency",
    "infer_era",
    "is_ufofiles",
    "main",
]

#: Tracked output artifact (under ``data/``, never an ignored directory).
OUTPUT_PATH = Path("data") / "provenance" / "source-index.json"

# spec §2a -- WHY this whole tree is excluded rather than indexed. The Black
# Vault ``UFOFiles/`` directory holds only mirrors of the PURSUE releases
# (four release ZIPs plus extracted media, uploaded 3-4 days after each war.gov
# release, under war.gov's own filenames). Of 73 PURSUE cards matched to a file
# there, 73 of 73 postdate their PURSUE release and zero precede it. Indexing it
# as a candidate prior-disclosure source would report PURSUE's own material as
# "previously disclosed" -- poisoning the candidate set at scale.
UFOFILES_EXCLUSION_REASON = (
    "Excluded per spec §2a: the UFOFiles/ tree contains only mirrors of the "
    "PURSUE releases themselves (73/73 matched files postdate their PURSUE "
    "release; zero precede it). Indexing it as a candidate prior-disclosure "
    "source would report PURSUE's own material as previously disclosed."
)

#: Why a row can be dropped for its URL alone — published beside the count.
INVALID_URL_EXCLUSION_REASON = (
    "Dropped: a sitemap <loc> is a third-party string and a catalogue row is one "
    "hop from a citation, so a row whose URL is not plain http(s) is excluded "
    "rather than carried into the artifact."
)

_SCHEMA = "sitemap-source-index/v1"

#: Path segments that name a releasing agency / archive collection. Inference is
#: deliberately conservative — an unrecognised segment yields ``"unknown"``.
_AGENCY_BY_SEGMENT: dict[str, str] = {
    "cbp": "cbp",
    "cia": "cia",
    "fbi": "fbi",
    "nsa": "nsa",
    "dia": "dia",
    "dhs": "dhs",
    "faa": "faa",
    "army": "army",
    "navy": "navy",
    "airforce": "air_force",
    "usaf": "air_force",
    "nasa": "nasa",
    "odni": "odni",
    "dod": "dod",
    "nara": "nara",
    "archives": "nara",
    "nationalarchives": "nara",
    "projectbluebook": "project_blue_book",
    "bluebook": "project_blue_book",
}


def is_ufofiles(url: str) -> bool:
    """True iff ``url`` lies under the ``UFOFiles/`` mirror tree (spec §2a)."""
    return "/ufofiles/" in urlparse(url).path.lower() + "/"


def infer_agency(url: str) -> str:
    """Infer the releasing agency from the URL path, or ``"unknown"``.

    The first path segment matching a known agency/collection wins; matching is
    conservative so an unfamiliar path is never mislabelled.
    """
    for segment in urlparse(url).path.lower().split("/"):
        agency = _AGENCY_BY_SEGMENT.get(segment)
        if agency is not None:
            return agency
    return "unknown"


def infer_era(url: str) -> tuple[str, int | None]:
    """Infer an era slug + year from a four-digit year in the path.

    Reuses the existing era buckets. Absent a defensible year the row is ``undated``.
    This is a weak triage hint derived from the path — **never** from the
    ``Last-Modified`` mtime, which is not a document era (spec §6d).
    """
    year = parse_year(urlparse(url).path)
    if year is None:
        return "undated", None
    return era_for_year(year).value, year


@dataclass(frozen=True)
class SourceEntry:
    """One catalogue row: a candidate source URL and what we can infer about it.

    ``last_modified`` is the upstream value verbatim (or ``None``) and
    ``date_basis`` says where that value came from: a sitemap ``<lastmod>``
    element (:attr:`DateBasis.SITEMAP_LASTMOD`) or a ``Last-Modified`` response
    header (:attr:`DateBasis.HTTP_LAST_MODIFIED`). Neither is a publication
    date (spec §6d) — the basis is stated so a consumer knows which evidence it
    holds and, since the two routes are written in different syntaxes, how to
    read the value. Every row states its basis; there is no default, so no row
    can carry a value under a basis nobody chose for it.
    """

    url: str
    filename: str
    last_modified: str | None
    agency: str
    era: str
    era_year: int | None
    date_basis: DateBasis

    def __post_init__(self) -> None:
        """A row is only usable when its URL is an address a reader can follow.

        ``url`` comes verbatim from a third-party sitemap ``<loc>`` and is one
        hop upstream of a citation — the resolver copies a matched row's URL
        into a claim's ``artifact_url``. Establishing that at the row means the
        rule holds for every path into the catalogue, including the stored
        artifact, rather than only at claim construction. Callers enumerating
        third-party input drop the row instead of propagating the error (see
        :func:`entry_from_url`).
        """
        require_web_url(self.url, "url")

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "filename": self.filename,
            "last_modified": self.last_modified,
            "date_basis": self.date_basis.value,
            "agency": self.agency,
            "era": self.era,
            "era_year": self.era_year,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceEntry:
        return cls(
            url=data["url"],
            filename=data["filename"],
            last_modified=data.get("last_modified"),
            agency=data["agency"],
            era=data["era"],
            era_year=data.get("era_year"),
            date_basis=DateBasis(data["date_basis"]),
        )


def entry_from_url(loc: str, lastmod: str | None) -> SourceEntry | None:
    """Build a :class:`SourceEntry` from a sitemap ``<loc>``, or ``None``.

    ``lastmod`` is the sitemap's ``<lastmod>`` element, so the row is built with
    :attr:`DateBasis.SITEMAP_LASTMOD` — the basis this route actually supplies,
    and the one that says the value reads as ISO 8601.

    A ``<loc>`` that is not an http(s) URL yields ``None`` so the caller can drop
    and count it. Enumeration runs over ~150k third-party URLs, so a row the
    catalogue cannot use is worth exactly that row — never the whole build — and
    a dropped row is counted rather than silently absent.
    """
    era, year = infer_era(loc)
    try:
        return SourceEntry(
            url=loc,
            filename=urlparse(loc).path.rstrip("/").rsplit("/", 1)[-1],
            last_modified=lastmod,
            agency=infer_agency(loc),
            era=era,
            era_year=year,
            date_basis=DateBasis.SITEMAP_LASTMOD,
        )
    except ValueError:
        return None


def entries_from_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[SourceEntry], int]:
    """Deserialise stored catalogue rows, dropping and counting unusable ones.

    A written artifact is an input on the next run, so it gets the same
    treatment as a live sitemap: a row that cannot yield an entry is skipped and
    counted, never fatal. "Cannot yield an entry" covers every shape JSON
    permits — a row that is not a mapping, a missing field, a ``url`` that is
    not text, and a ``url`` that is text but not a web address — because a
    stored artifact is edited by hand and written by future producers, and the
    load's contract is to return the rows it *can* read.
    """
    entries: list[SourceEntry] = []
    dropped = 0
    for row in rows:
        try:
            entries.append(SourceEntry.from_dict(row))
        except (ValueError, KeyError, TypeError):
            dropped += 1
    return entries, dropped


@dataclass(frozen=True)
class Catalogue:
    """The assembled catalogue: kept entries plus the exclusion bookkeeping."""

    entries: tuple[SourceEntry, ...]
    total_urls: int
    excluded_ufofiles: int
    sitemap_index_urls: tuple[str, ...] = field(default_factory=tuple)
    excluded_invalid_url: int = 0


def build_catalogue(
    rows: Iterable[UrlRow],
    sitemap_index_urls: Sequence[str] = (),
) -> Catalogue:
    """Assemble a catalogue from parsed sitemap rows, dropping the UFOFiles tree.

    Every ``UFOFiles/`` row is excluded (spec §2a) and counted; the total seen
    is recorded so the exclusion is auditable rather than silent.
    """
    entries: list[SourceEntry] = []
    total = 0
    excluded = 0
    invalid = 0
    for row in rows:
        total += 1
        if is_ufofiles(row.loc):
            excluded += 1
            continue
        entry = entry_from_url(row.loc, row.lastmod)
        if entry is None:
            invalid += 1
            continue
        entries.append(entry)
    return Catalogue(
        entries=tuple(entries),
        total_urls=total,
        excluded_ufofiles=excluded,
        sitemap_index_urls=tuple(sitemap_index_urls),
        excluded_invalid_url=invalid,
    )


def _fetchable(url: str, host: str | None) -> bool:
    """A URL is followed only if it is a listing *on the enumerated host*.

    The enumeration's scope is one host's published sitemaps, and the URLs that
    name its children come from those sitemaps themselves. Pinning every fetch
    to the ``robots.txt`` host keeps the scope decided here rather than by the
    documents being read — the same rule the asset downloader applies.
    """
    return is_listing_url(url) and urlparse(url).hostname == host


def build_catalogue_from_fetcher(fetcher: CourteousFetcher, robots_url: str) -> Catalogue:
    """Enumerate robots → sitemap indexes → sitemaps → rows, and assemble.

    Only listings *on the robots host* are ever fetched (the ``fetcher`` also
    refuses non-listings), so no PDF is downloaded and the enumeration stays on
    the host it set out to enumerate. Off-host or non-listing children are
    skipped rather than fetched.
    """
    host = urlparse(robots_url).hostname
    index_urls = parse_robots_sitemaps(fetcher.fetch(robots_url).body)
    rows: list[Any] = []
    for index_url in index_urls:
        if not _fetchable(index_url, host):
            continue
        for child in parse_sitemap_index(fetcher.fetch(index_url).body):
            if not _fetchable(child, host):
                continue
            rows.extend(parse_url_entries(fetcher.fetch(child).body))
    return build_catalogue(rows, index_urls)


def build_output(catalogue: Catalogue, robots_url: str) -> dict[str, Any]:
    """Assemble the tracked, regenerable artifact from a catalogue."""
    return {
        "schema": _SCHEMA,
        "robots_url": robots_url,
        "sitemap_index_urls": list(catalogue.sitemap_index_urls),
        "date_basis": DateBasis.SITEMAP_LASTMOD.value,
        "total_urls_seen": catalogue.total_urls,
        "ufofiles_excluded": {
            "count": catalogue.excluded_ufofiles,
            "reason": UFOFILES_EXCLUSION_REASON,
        },
        "invalid_urls_excluded": {
            "count": catalogue.excluded_invalid_url,
            "reason": INVALID_URL_EXCLUSION_REASON,
        },
        "entry_count": len(catalogue.entries),
        "agency_counts": dict(Counter(e.agency for e in catalogue.entries)),
        "era_counts": dict(Counter(e.era for e in catalogue.entries)),
        "entries": [e.to_dict() for e in catalogue.entries],
    }


def _default_get(url: str) -> httpx.Response:
    """Live HTTP GET for a listing — one request, courteous UA, no retries.

    ``follow_redirects=False`` is load-bearing. ``_fetchable`` decides the host
    before the request is made; a redirect is decided by the response, after
    that check, so following one would move the scope decision out of this
    module and into the server. A 3xx is surfaced to the caller instead, which
    aborts on any non-2xx.
    """
    return httpx.get(
        url,
        timeout=30.0,
        follow_redirects=False,
        headers={"User-Agent": "pursue-index-source-catalogue/1.0 (provenance Phase A; index only)"},
    )


def main() -> int:
    """CLI: enumerate the published sitemap indexes live → the tracked artifact.

    This is the operator's regeneration step; it makes real (but courteous,
    listing-only) requests. On a non-2xx it aborts with a clear message rather
    than retrying in a loop.
    """
    repo_root = Path(__file__).resolve().parents[2]
    out_path = repo_root / OUTPUT_PATH
    fetcher = CourteousFetcher(get=_default_get)
    try:
        catalogue = build_catalogue_from_fetcher(fetcher, DEFAULT_ROBOTS_URL)
    except SitemapFetchError as exc:
        print(f"source-index: aborted — {exc}")
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build_output(catalogue, DEFAULT_ROBOTS_URL), indent=2) + "\n")
    print(
        f"source-index: {len(catalogue.entries)} entries "
        f"({catalogue.excluded_ufofiles} UFOFiles rows excluded per §2a) "
        f"from {catalogue.total_urls} URLs"
    )
    print(f"  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
