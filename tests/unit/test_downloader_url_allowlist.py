"""Asset-URL allowlist for the download stage.

``download_all`` fetches ``card.asset_url`` from the upstream war.gov CSV. A
compromised/spoofed upstream — or an operator-approved tranche whose asset URLs
were tampered with — must not turn the download fan-out into an SSRF /
arbitrary-fetch primitive (the ``ingest run --from-diff`` path automates this
behind a human approval gate, so the gate attests legitimacy, not URL safety).
The downloader validates scheme + host before fetching and skips anything off
the allowlist.
"""

from __future__ import annotations

import httpx
import pytest

from pursue_index.config import settings
from pursue_index.download.downloader import _download_one, _is_allowed_asset_url
from pursue_index.scrape.types import CardMetadata


def _card(**overrides) -> CardMetadata:
    defaults = {
        "card_id": "abc1234567890def",
        "title": "Test card",
        "asset_type": "PDF",
        "agency": "Test",
        "redacted": False,
    }
    defaults.update(overrides)
    return CardMetadata.model_construct(**defaults)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.war.gov/Portals/1/x.pdf",
        "https://war.gov/x.pdf",  # apex variant
    ],
)
def test_allows_official_https_hosts(url: str) -> None:
    assert _is_allowed_asset_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.war.gov/x.pdf",  # not https
        "https://evil.com/x.pdf",  # wrong host
        "https://www.war.gov.evil.com/x.pdf",  # suffix-spoof host
        "https://warxgov/x.pdf",
        "ftp://www.war.gov/x.pdf",  # wrong scheme
        "file:///etc/passwd",
        "",
    ],
)
def test_rejects_off_allowlist_urls(url: str) -> None:
    assert _is_allowed_asset_url(url) is False


async def test_download_one_skips_disallowed_host_without_fetching(tmp_path, monkeypatch) -> None:
    """A disallowed URL must be skipped (return None) and NEVER hit the network."""
    monkeypatch.setattr(type(settings), "pdf_dir", property(lambda self: tmp_path))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x")

    card = _card(asset_url="https://evil.com/x.pdf", asset_filename="x.pdf")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _download_one(client, card)
    assert result is None
    assert calls == [], "disallowed URL must never be fetched"


async def test_download_one_fetches_allowed_host(tmp_path, monkeypatch) -> None:
    """The happy path is unchanged: an allowed URL is fetched and written."""
    monkeypatch.setattr(type(settings), "pdf_dir", property(lambda self: tmp_path))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"PDFBYTES")

    card = _card(asset_url="https://www.war.gov/x.pdf", asset_filename="x.pdf")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _download_one(client, card)
    assert result is not None
    assert result.read_bytes() == b"PDFBYTES"
    assert calls == ["https://www.war.gov/x.pdf"]
