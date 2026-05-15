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

    monkeypatch.setattr(csv_fetcher, "http_get", fake_get)

    raw = fetch_raw_csv()

    assert raw == _SAMPLE_CSV
    assert isinstance(captured.get("impersonate"), str)
    assert "chrome" in str(captured["impersonate"]).lower()


def test_fetch_raw_csv_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        csv_fetcher,
        "http_get",
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


_CSV_WITH_A11Y_META = (
    "﻿Redaction,Release Date,Title,Type,Video Pairing,PDF Pairing,"
    "Description Blurb,DVIDS Video ID,Video Title,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Image Alt Text,Image VIRIN\r\n"
    'True,5/8/26,"\nCase 0001 Section 1\n",PDF ,,,Brief.,,,FBI,1/15/95,'
    '"Roswell, NM",'
    "https://www.war.gov/case_0001.pdf,"
    "https://www.war.gov/img/case_0001.jpg,"
    "Declassified Secret document from Air Materiel Command.,"
    "260508-D-D0360-1001\r\n"
    ",4/1/26,Card Without Alt,PDF,,,Brief.,,,FBI,N/A,N/A,"
    "https://www.war.gov/case_0002.pdf,,,\r\n"
).encode("utf-8")


def test_parse_csv_captures_image_alt_text_and_virin() -> None:
    """Tranche c9cc83fcaf43 added Image Alt Text + Image VIRIN columns.

    These are upstream-curated DoD accessibility metadata (Section 508
    alt-text + DoDI 5040.02 VIRIN). The web renderer prefers them over
    auto-generated alts when present.
    """
    cards = parse_csv(_CSV_WITH_A11Y_META)
    assert len(cards) == 2

    with_meta, without_meta = cards
    assert with_meta.image_alt_text == "Declassified Secret document from Air Materiel Command."
    assert with_meta.image_virin == "260508-D-D0360-1001"

    # Empty CSV cells normalize to None (not "" or "N/A")
    assert without_meta.image_alt_text is None
    assert without_meta.image_virin is None


def test_image_alt_text_and_virin_not_duplicated_in_raw() -> None:
    """Once a column is promoted to a typed field, it should not also
    leak into the raw forward-compat dict — that defeats the schema.
    """
    cards = parse_csv(_CSV_WITH_A11Y_META)
    assert "Image Alt Text" not in cards[0].raw
    assert "Image VIRIN" not in cards[0].raw


_CSV_WITH_CLASSIFICATIONS = (
    "﻿Redaction,Release Date,Title,Type,Video Pairing,PDF Pairing,"
    "Description Blurb,DVIDS Video ID,Video Title,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Image Alt Text,Image VIRIN\r\n"
    "True,5/8/26,A,PDF,,,B,,,FBI,,,https://x/a.pdf,,"
    "Declassified Top Secret document from the U.S. Air Force.,260508-D-D0360-1001\r\n"
    "True,5/8/26,B,PDF,,,B,,,FBI,,,https://x/b.pdf,,"
    "Declassified Secret document from Air Materiel Command.,260508-D-D0360-1002\r\n"
    "True,5/8/26,C,PDF,,,B,,,FBI,,,https://x/c.pdf,,"
    "Declassified Confidential document from the U.S. Air Force.,260508-D-D0360-1003\r\n"
    "True,5/8/26,D,PDF,,,B,,,FBI,,,https://x/d.pdf,,"
    "Declassified Restricted document from Lowry Flight Service Center.,260508-D-D0360-1004\r\n"
    "True,5/8/26,E,PDF,,,B,,,State,,,https://x/e.pdf,,"
    "Unclassified diplomatic cable from the US Department of State.,260508-D-D0360-1005\r\n"
    "True,5/8/26,F,PDF,,,B,,,FBI,,,https://x/f.pdf,,"
    "Declassified FBI file cover from the Central Records Center.,260508-D-D0360-1006\r\n"
).encode("utf-8")


def test_original_classification_extracted_from_alt_text() -> None:
    """Tranche c9cc83fcaf43 alt-text embeds the original document
    classification ("Declassified Top Secret document..."). Extract
    it into a structured field so the renderer can surface it as a
    badge / search filter.
    """
    cards = parse_csv(_CSV_WITH_CLASSIFICATIONS)
    assert cards[0].original_classification == "Top Secret"
    assert cards[1].original_classification == "Secret"
    assert cards[2].original_classification == "Confidential"
    assert cards[3].original_classification == "Restricted"
    assert cards[4].original_classification == "Unclassified"
    # Generic "Declassified FBI file cover" with no level keyword → None
    # (Upstream didn't specify; we honor that rather than guessing.)
    assert cards[5].original_classification is None


def test_original_classification_none_when_no_alt_text() -> None:
    """No alt-text → no classification (don't invent one)."""
    cards = parse_csv(_CSV_WITH_A11Y_META)
    # Second sample card has no alt-text at all
    assert cards[1].image_alt_text is None
    assert cards[1].original_classification is None
