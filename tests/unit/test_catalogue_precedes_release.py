"""Catalogue evidence counts as prior only when it predates the release (§6).

A catalogue match says an archive holds a document under the identifier the card
carries. What makes that a *prior* release is the one comparison this module
pins: the row's own date has to fall strictly before the card's release date.

The catalogue is enumerated live from a third-party host, so it holds rows of
every vintage — including mirrors of material published after the release under
examination, and rows in whatever order the sitemaps list them. So the
comparison decides every catalogue-dated claim:

* a row dated on or after the release date establishes nothing prior, and the
  search carries on to the rest of the candidates rather than stopping at it;
* a card whose own release date cannot be read supplies nothing to compare
  against, so catalogue evidence yields no dated claim for it at all;
* a row dated before the release date resolves exactly as it always does.
"""

from __future__ import annotations

from datetime import date

import pytest

from pursue_index.identifier_resolver import resolve_card
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.source_index import SourceEntry

_TITLE = "The 62-HQ-83894 case file records"
_RELEASE = "5/8/26"  # 2026-05-08, as the corpus writes it

_BEFORE = "2015-06-01T00:00:00Z"
_SAME_DAY = "2026-05-08T00:00:00Z"
_AFTER = "2026-06-01T00:00:00Z"


def _card(release_date: str | None = _RELEASE) -> dict:
    card = {"card_id": "fbi-prior", "title": _TITLE}
    if release_date is not None:
        card["release_date"] = release_date
    return card


def _entry(slug: str, lastmod: str) -> SourceEntry:
    url = f"https://documents.theblackvault.com/fbi/{slug}/62-hq-83894.pdf"
    return SourceEntry(
        url=url,
        filename="62-hq-83894.pdf",
        last_modified=lastmod,
        agency="fbi",
        era="undated",
        era_year=None,
        date_basis=DateBasis.SITEMAP_LASTMOD,
    )


@pytest.mark.parametrize("lastmod", [_AFTER, _SAME_DAY])
def test_a_match_not_older_than_the_release_yields_no_claim(lastmod: str) -> None:
    """Evidence dated on or after the release establishes nothing prior to it."""
    assert resolve_card(_card(), catalogue=[_entry("mirror", lastmod)]) == []


def test_the_search_continues_past_a_match_that_is_not_prior() -> None:
    """A later-dated row is one candidate, not the end of the candidates."""
    catalogue = [_entry("mirror", _AFTER), _entry("original", _BEFORE)]
    claims = resolve_card(_card(), catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].established_date == date(2015, 6, 1)
    assert claims[0].artifact_url.endswith("/original/62-hq-83894.pdf")


def test_a_card_without_a_readable_release_date_takes_no_catalogue_claim() -> None:
    """With nothing to compare against, "prior" is not established at all."""
    assert resolve_card(_card(release_date=None), catalogue=[_entry("original", _BEFORE)]) == []
    assert resolve_card(_card(release_date="undated"), catalogue=[_entry("original", _BEFORE)]) == []


def test_a_match_older_than_the_release_resolves_as_a_prior_release() -> None:
    claims = resolve_card(_card(), catalogue=[_entry("original", _BEFORE)])
    assert len(claims) == 1
    assert claims[0].tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert claims[0].established_date == date(2015, 6, 1)
