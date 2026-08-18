"""Tests for the sitemap-derived source catalogue.

The catalogue is the local index of *candidate* prior-disclosure sources — one
row per URL with its filename, the sitemap's last-modified value and the basis
that value rests on, and an inferred agency and era. Three disciplines are
load-bearing and covered here:

* **The ``UFOFiles/`` tree is excluded** (spec §2a): it holds only mirrors of
  the PURSUE releases and would poison the candidate set.
* **No PDF is ever fetched.** The whole build runs through the courteous
  fetcher, which only ever touches listings; the ``<loc>`` PDF URLs are
  *recorded*, never requested.
* **A last-modified value is stored under the basis it came from, never as a
  publication date** (spec §6d: these values are bulk-migration mtimes). Rows
  built from sitemaps carry ``sitemap_lastmod``. Era is inferred from the
  path/filename instead, independently of the mtime.
"""

from __future__ import annotations

import json
from typing import NamedTuple

import pytest

from pursue_index.provenance import DateBasis
from pursue_index.sitemap_fetch import CourteousFetcher
from pursue_index.source_index import (
    UFOFILES_EXCLUSION_REASON,
    SourceEntry,
    build_catalogue,
    build_catalogue_from_fetcher,
    build_output,
    entry_from_url,
    infer_agency,
    infer_era,
    is_ufofiles,
)

# --------------------------------------------------------------------------
# Exclusion of the UFOFiles/ mirror tree (spec §2a).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://documents3.theblackvault.com/UFOFiles/release-1.zip",
        "https://documents3.theblackvault.com/ufofiles/x.pdf",
        "https://host/a/UFOFiles/b/c.pdf",
    ],
)
def test_ufofiles_tree_is_recognised(url: str) -> None:
    assert is_ufofiles(url)


def test_non_ufofiles_paths_are_kept() -> None:
    assert not is_ufofiles("https://documents3.theblackvault.com/cbp/report.pdf")


def test_exclusion_reason_cites_spec_2a() -> None:
    assert "§2a" in UFOFILES_EXCLUSION_REASON


# --------------------------------------------------------------------------
# Inference.
# --------------------------------------------------------------------------


def test_infer_agency_from_path_segment() -> None:
    assert infer_agency("https://host/cbp/report.pdf") == "cbp"
    assert infer_agency("https://host/cia/ufos/x.pdf") == "cia"
    assert infer_agency("https://host/projectbluebook/case.pdf") == "project_blue_book"


def test_infer_agency_unknown_when_no_known_segment() -> None:
    assert infer_agency("https://host/misc/thing.pdf") == "unknown"


def test_infer_era_from_year_in_path() -> None:
    slug, year = infer_era("https://host/cia/ufos/1952-sighting.pdf")
    assert (slug, year) == ("pre_1970", 1952)


def test_infer_era_undated_when_no_year() -> None:
    assert infer_era("https://host/cbp/report.pdf") == ("undated", None)


# --------------------------------------------------------------------------
# SourceEntry — a row that states the basis its last-modified value rests on.
# --------------------------------------------------------------------------


def test_entry_records_filename_and_sitemap_lastmod_basis() -> None:
    entry = entry_from_url(
        "https://host/cbp/2021/incident-report.pdf",
        "2020-05-30T09:12:00Z",
    )
    assert entry.filename == "incident-report.pdf"
    assert entry.agency == "cbp"
    assert entry.era == "2015_plus"
    assert entry.era_year == 2021
    assert entry.last_modified == "2020-05-30T09:12:00Z"
    # The mtime is never a publication date, and the row states where the value
    # came from: the sitemap's <lastmod> element, which reads as ISO 8601.
    assert entry.date_basis is DateBasis.SITEMAP_LASTMOD


def test_entry_roundtrips_through_dict() -> None:
    entry = entry_from_url("https://host/cbp/report.pdf", None)
    restored = SourceEntry.from_dict(entry.to_dict())
    assert restored == entry
    assert entry.to_dict()["date_basis"] == DateBasis.SITEMAP_LASTMOD.value


# --------------------------------------------------------------------------
# build_catalogue — filters the UFOFiles tree.
# --------------------------------------------------------------------------


class _Row(NamedTuple):
    loc: str
    lastmod: str | None


def test_build_catalogue_drops_ufofiles_entries() -> None:
    rows = [
        _Row("https://host/cbp/keep.pdf", "Sat, 30 May 2020 09:12:00 GMT"),
        _Row("https://host/UFOFiles/mirror.pdf", None),
        _Row("https://host/cia/ufos/1965-file.pdf", None),
    ]
    catalogue = build_catalogue(rows)
    urls = [e.url for e in catalogue.entries]
    assert "https://host/UFOFiles/mirror.pdf" not in urls
    assert len(catalogue.entries) == 2
    assert catalogue.excluded_ufofiles == 1
    assert catalogue.total_urls == 3


# --------------------------------------------------------------------------
# End-to-end build over the real fetcher wired to fixture bytes — no socket,
# and crucially: never a PDF request.
# --------------------------------------------------------------------------

_ROBOTS = (
    "User-agent: *\n"
    "Sitemap: https://host/sitemap-index-1.xml\n"
    "Sitemap: https://host/sitemap-index-2.xml\n"
)

_INDEX_1 = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://host/sitemap-a.xml</loc></sitemap>
</sitemapindex>"""

_INDEX_2 = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://host/sitemap-b.xml</loc></sitemap>
</sitemapindex>"""

_SITEMAP_A = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://host/cbp/2021/report.pdf</loc><lastmod>2020-05-30T09:12:00Z</lastmod></url>
  <url><loc>https://host/UFOFiles/release-1.zip</loc><lastmod>2026-05-11T00:00:00Z</lastmod></url>
</urlset>"""

_SITEMAP_B = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://host/projectbluebook/1952-case.pdf</loc></url>
</urlset>"""

_FIXTURE_BYTES = {
    "https://host/robots.txt": _ROBOTS,
    "https://host/sitemap-index-1.xml": _INDEX_1,
    "https://host/sitemap-index-2.xml": _INDEX_2,
    "https://host/sitemap-a.xml": _SITEMAP_A,
    "https://host/sitemap-b.xml": _SITEMAP_B,
}


class _FixtureResp(NamedTuple):
    status_code: int
    text: str
    headers: dict[str, str]


class _FixtureNet:
    """A fake ``get`` backed by fixture bytes; records every URL requested."""

    def __init__(self, bytes_by_url: dict[str, str]) -> None:
        self._bytes = bytes_by_url
        self.requested: list[str] = []

    def get(self, url: str) -> _FixtureResp:
        self.requested.append(url)
        return _FixtureResp(200, self._bytes[url], {"Last-Modified": "Sat, 30 May 2020 09:12:00 GMT"})

    def sleep(self, _seconds: float) -> None:  # courtesy delay, no-op in tests
        return None


def _build_from_fixtures() -> tuple[_FixtureNet, object]:
    net = _FixtureNet(_FIXTURE_BYTES)
    fetcher = CourteousFetcher(get=net.get, sleep=net.sleep, delay=0.0)
    catalogue = build_catalogue_from_fetcher(fetcher, "https://host/robots.txt")
    return net, catalogue


def test_end_to_end_build_catalogues_all_four_hosts_worth_of_entries() -> None:
    _net, catalogue = _build_from_fixtures()
    urls = {e.url for e in catalogue.entries}
    assert urls == {
        "https://host/cbp/2021/report.pdf",
        "https://host/projectbluebook/1952-case.pdf",
    }
    assert list(catalogue.sitemap_index_urls) == [
        "https://host/sitemap-index-1.xml",
        "https://host/sitemap-index-2.xml",
    ]
    assert catalogue.excluded_ufofiles == 1


def test_end_to_end_never_requests_a_pdf_or_the_excluded_tree() -> None:
    net, _catalogue = _build_from_fixtures()
    # Only listings were ever requested — no PDF, no zip, no UFOFiles asset.
    assert all(is_listing(url) for url in net.requested), net.requested


def is_listing(url: str) -> bool:
    return url.endswith(".xml") or url.endswith("robots.txt")


def test_end_to_end_never_follows_an_off_host_sitemap() -> None:
    # A tampered index that points at another host must not steer the fan-out
    # off-scope: the off-host sitemap is skipped, never fetched.
    robots = "Sitemap: https://host/sitemap-index-1.xml\n"
    index = (
        '<?xml version="1.0"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <sitemap><loc>https://host/sitemap-a.xml</loc></sitemap>\n"
        "  <sitemap><loc>https://evil.example.com/sitemap-evil.xml</loc></sitemap>\n"
        "</sitemapindex>"
    )
    net = _FixtureNet(
        {
            "https://host/robots.txt": robots,
            "https://host/sitemap-index-1.xml": index,
            "https://host/sitemap-a.xml": _SITEMAP_A,
        }
    )
    fetcher = CourteousFetcher(get=net.get, sleep=net.sleep, delay=0.0)
    catalogue = build_catalogue_from_fetcher(fetcher, "https://host/robots.txt")

    assert "https://evil.example.com/sitemap-evil.xml" not in net.requested
    # cbp kept, the UFOFiles row in sitemap-a excluded.
    assert [e.agency for e in catalogue.entries] == ["cbp"]


def test_end_to_end_entries_carry_inferred_agency_era_and_sitemap_basis() -> None:
    _net, catalogue = _build_from_fixtures()
    by_agency = {e.agency: e for e in catalogue.entries}
    assert by_agency["cbp"].era == "2015_plus"
    assert by_agency["cbp"].era_year == 2021
    assert by_agency["project_blue_book"].era == "pre_1970"
    for entry in catalogue.entries:
        assert entry.date_basis is DateBasis.SITEMAP_LASTMOD


# --------------------------------------------------------------------------
# Regenerable artifact.
# --------------------------------------------------------------------------


def test_build_output_is_json_serialisable_and_carries_exclusion_reason() -> None:
    _net, catalogue = _build_from_fixtures()
    output = build_output(catalogue, robots_url="https://host/robots.txt")
    text = json.dumps(output, indent=2)  # must not raise
    restored = json.loads(text)
    assert restored["ufofiles_excluded"]["count"] == 1
    assert "§2a" in restored["ufofiles_excluded"]["reason"]
    assert restored["entry_count"] == 2
    assert restored["date_basis"] == DateBasis.SITEMAP_LASTMOD.value
    assert len(restored["entries"]) == 2
