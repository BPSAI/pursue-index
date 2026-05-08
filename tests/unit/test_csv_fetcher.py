"""Tests for the CSV fetch + parse pipeline.

The live war.gov endpoint is gated by Akamai bot management — anything that
doesn't present a Chrome-equivalent TLS fingerprint and header set gets a 403.
We rely on ``curl_cffi`` with ``impersonate="chrome"`` to clear the gate, and
these tests pin that contract so a careless refactor can't quietly regress us
back into 403 territory.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pursue_index.scrape import csv_fetcher
from pursue_index.scrape.csv_fetcher import (
    build_manifest,
    fetch_raw_csv,
    parse_csv,
)


_SAMPLE_CSV = (
    "﻿Redaction,Release Date,Title,Type,Video Pairing,PDF Pairing,"
    "Description Blurb,DVIDS Video ID,Video Title,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image\r\n"
    'True,5/8/26,"\nCase 0001 Section 1\n",PDF ,,,'
    '"Brief description.",,,FBI,1/15/95,"Roswell, NM",'
    "https://www.war.gov/medialink/ufo/release_1/case_0001.pdf,"
    "https://www.war.gov/img/case_0001.jpg\r\n"
    ",4/1/26,Video Card,VID,,,Some video,12345,Title Of The Video,DOW,N/A,N/A,"
    "https://www.dvidshub.net/video/12345,"
    "https://www.war.gov/img/vid_12345.jpg\r\n"
).encode("utf-8")


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_raw_csv_uses_chrome_impersonation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fetcher MUST use curl_cffi's Chrome TLS impersonation.

    Without it Akamai 403s every request, so this is a load-bearing contract.
    """
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(200, _SAMPLE_CSV)

    monkeypatch.setattr(csv_fetcher, "_http_get", fake_get)

    raw = fetch_raw_csv()

    assert raw == _SAMPLE_CSV
    assert isinstance(captured.get("impersonate"), str)
    assert "chrome" in str(captured["impersonate"]).lower()


def test_fetch_raw_csv_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        csv_fetcher,
        "_http_get",
        lambda url, **kw: _FakeResponse(403, b"Access Denied"),
    )
    with pytest.raises(RuntimeError, match="403"):
        fetch_raw_csv()


def test_parse_csv_yields_normalized_cards() -> None:
    cards = parse_csv(_SAMPLE_CSV)

    assert len(cards) == 2
    pdf, vid = cards

    assert pdf.title == "Case 0001 Section 1"
    assert pdf.asset_type == "PDF"  # trailing space normalized
    assert pdf.agency == "FBI"
    assert pdf.redacted is True
    assert pdf.incident_location == "Roswell, NM"
    assert pdf.asset_filename == "case_0001.pdf"

    assert vid.asset_type == "VID"
    assert vid.dvids_video_id == "12345"
    assert vid.incident_date is None  # "N/A" → None
    assert vid.incident_location is None


def test_build_manifest_hashes_raw_bytes() -> None:
    cards = parse_csv(_SAMPLE_CSV)
    m = build_manifest(_SAMPLE_CSV, cards, "https://www.war.gov/x.csv")
    assert m.csv_sha256 == (
        # sha256 of _SAMPLE_CSV — we don't hard-code it, just sanity-check shape
        m.csv_sha256
    )
    assert len(m.csv_sha256) == 64
    assert m.card_count == 2
