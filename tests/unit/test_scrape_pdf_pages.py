"""The poll lane fetches each new PDF and counts its pages (R7C.5).

``pursue_index.scrape.pdf_pages`` picks the tranche's new or byte-changed PDF
cards, fetches each through the same Chrome-impersonation client the PDF
health check uses (``csv_fetcher.http_get``), counts pages, and keeps the bytes
only in a temporary directory for the life of the ``with`` block (R7C.31's
classifier reads them there). A card whose fetch fails is reported as a
per-card fallback instead of raising.
"""

from __future__ import annotations

import pytest

from pursue_index.release.rates import RATES_TABLE, cost_band
from pursue_index.scrape import csv_fetcher
from pursue_index.scrape.pdf_pages import PageTarget, fetch_and_count
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes

_BASE = "https://www.war.gov/medialink/ufo"
_THREE = {f"{_BASE}/p{n}.pdf": pdf_bytes(n) for n in (1, 10, 100)}


def _targets() -> list[PageTarget]:
    return [PageTarget(card_id=f"card{n:03d}", url=f"{_BASE}/p{n}.pdf") for n in (1, 10, 100)]


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> FakeHttpGet:
    fake = FakeHttpGet(bodies=_THREE)
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    return fake


def test_three_fixture_pdfs_count_111_pages_and_price_to_the_table(fake_get) -> None:
    with fetch_and_count(_targets()) as fetched:
        assert fetched.page_counts == {"card001": 1, "card010": 10, "card100": 100}
        assert fetched.fallback_card_ids == []
        band = cost_band(sum(fetched.page_counts.values()))
    assert band.pages == 111
    assert band.low == pytest.approx(111 * sum(r.low for r in RATES_TABLE.values()))
    assert band.high == pytest.approx(111 * sum(r.high for r in RATES_TABLE.values()))


def test_fetch_uses_the_chrome_impersonation_client(fake_get) -> None:
    with fetch_and_count(_targets()):
        pass
    assert [url for url, _ in fake_get.calls] == [t.url for t in _targets()]
    assert all(kw.get("impersonate") == "chrome" for _, kw in fake_get.calls)


def test_a_failed_fetch_is_a_per_card_fallback_and_the_band_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeHttpGet(bodies=_THREE, fail=frozenset({f"{_BASE}/p10.pdf"}))
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count(_targets()) as fetched:
        assert fetched.fallback_card_ids == ["card010"]
        assert fetched.page_counts == {"card001": 1, "card100": 100}
        band = cost_band(101, fallback_card_ids=fetched.fallback_card_ids)
    assert band.partial is True
    assert band.fallback_card_ids == ("card010",)


def test_http_errors_and_unparseable_bytes_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies = {f"{_BASE}/p1.pdf": b"<html>Access Denied</html>"}  # p10/p100 absent -> 404
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies=bodies))
    with fetch_and_count(_targets()) as fetched:
        assert fetched.page_counts == {}
        assert fetched.fallback_card_ids == ["card001", "card010", "card100"]


def test_bytes_live_only_in_the_temp_dir_for_the_with_block(fake_get) -> None:
    with fetch_and_count(_targets()) as fetched:
        path = fetched.paths["card100"]
        assert path.parent == fetched.workdir
        assert path.read_bytes() == _THREE[f"{_BASE}/p100.pdf"]
    assert not fetched.workdir.exists()
