"""Sitemap-derived source catalogue (spec §2 and §3, §7 step 3; PV1.4).

A local index of *candidate* prior-disclosure sources, enumerated from the four
sitemap indexes leaked via ``documents3.theblackvault.com/robots.txt`` (spec
§2b: 157,628 URLs, of which the UFO-relevant slice is ~8,000). One row per URL:
its filename, HTTP ``Last-Modified``, and an inferred agency and era.

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
* **A ``Last-Modified`` is never a publication date — spec §6d.** Those values
  cluster in a five-minute window on 2020-05-30; they date "existed on this host
  by", not publication. Every row pins its ``last_modified`` to
  ``date_basis = http_last_modified`` and the *era* is inferred from the
  path/filename instead — independently of the mtime.
* **Era is inferred, not asserted.** A four-digit year in the path yields an era
  bucket (reusing PV1.3's :func:`~pursue_index.era_models.era_for_year`); absent
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
from pursue_index.provenance import DateBasis
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
    "OUTPUT_PATH",
    "UFOFILES_EXCLUSION_REASON",
    "Catalogue",
    "SourceEntry",
    "build_catalogue",
    "build_catalogue_from_fetcher",
    "build_output",
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

    Reuses PV1.3's era buckets. Absent a defensible year the row is ``undated``.
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

    ``last_modified`` is the HTTP header verbatim (or ``None``); ``date_basis``
    is fixed to :attr:`DateBasis.HTTP_LAST_MODIFIED` so the value can never be
    mistaken for a publication date (spec §6d).
    """

    url: str
    filename: str
    last_modified: str | None
    agency: str
    era: str
    era_year: int | None
    date_basis: DateBasis = DateBasis.HTTP_LAST_MODIFIED

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
            date_basis=DateBasis(data.get("date_basis", DateBasis.HTTP_LAST_MODIFIED.value)),
        )


def entry_from_url(loc: str, lastmod: str | None) -> SourceEntry:
    """Build a :class:`SourceEntry` from a sitemap ``<loc>`` + ``<lastmod>``."""
    filename = urlparse(loc).path.rstrip("/").rsplit("/", 1)[-1]
    era, year = infer_era(loc)
    return SourceEntry(
        url=loc,
        filename=filename,
        last_modified=lastmod,
        agency=infer_agency(loc),
        era=era,
        era_year=year,
    )


@dataclass(frozen=True)
class Catalogue:
    """The assembled catalogue: kept entries plus the exclusion bookkeeping."""

    entries: tuple[SourceEntry, ...]
    total_urls: int
    excluded_ufofiles: int
    sitemap_index_urls: tuple[str, ...] = field(default_factory=tuple)


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
    for row in rows:
        total += 1
        if is_ufofiles(row.loc):
            excluded += 1
            continue
        entries.append(entry_from_url(row.loc, row.lastmod))
    return Catalogue(
        entries=tuple(entries),
        total_urls=total,
        excluded_ufofiles=excluded,
        sitemap_index_urls=tuple(sitemap_index_urls),
    )


def _fetchable(url: str, host: str | None) -> bool:
    """A URL is followed only if it is a listing *on the enumerated host*.

    The sitemap indexes are third-party controlled; keeping the fetch fan-out
    pinned to the ``robots.txt`` host stops a tampered index from steering us
    off-scope (cf. the SSRF guard on the asset downloader).
    """
    return is_listing_url(url) and urlparse(url).hostname == host


def build_catalogue_from_fetcher(fetcher: CourteousFetcher, robots_url: str) -> Catalogue:
    """Enumerate robots → sitemap indexes → sitemaps → rows, and assemble.

    Only listings *on the robots host* are ever fetched (the ``fetcher`` also
    refuses non-listings), so no PDF is downloaded and the fan-out cannot be
    steered off-host by a tampered index. Off-host or non-listing children are
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
        "date_basis": DateBasis.HTTP_LAST_MODIFIED.value,
        "total_urls_seen": catalogue.total_urls,
        "ufofiles_excluded": {
            "count": catalogue.excluded_ufofiles,
            "reason": UFOFILES_EXCLUSION_REASON,
        },
        "entry_count": len(catalogue.entries),
        "agency_counts": dict(Counter(e.agency for e in catalogue.entries)),
        "era_counts": dict(Counter(e.era for e in catalogue.entries)),
        "entries": [e.to_dict() for e in catalogue.entries],
    }


def _default_get(url: str) -> httpx.Response:
    """Live HTTP GET for a listing — one request, courteous UA, no retries."""
    return httpx.get(
        url,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "pursue-index-source-catalogue/1.0 (provenance Phase A; index only)"},
    )


def main() -> int:
    """CLI: enumerate the leaked sitemaps live → the tracked artifact.

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
