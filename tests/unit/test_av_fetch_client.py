"""Tests for ``pursue_index.av_fetch.client`` — DVIDS page + asset fetch.

The probe run for T48.5 confirmed: DVIDS ``/video/<id>`` pages fetch fine via
the same curl_cffi Chrome-impersonation client used for war.gov
(``csv_fetcher.http_get``), and the direct DOD asset URL embedded in the page
markup (a ``<source ... type='video/mp4'>`` tag) is not CDN-blocked — a real
GET against it returned 200 / ``binary/octet-stream`` / 6,814,452 bytes for a
VID asset and 200 / ``binary/octet-stream`` / 19,126,276 bytes for an AUD
asset, both resolved via ``/video/<id>`` (never ``/audio/<id>``).

These tests pin the two seams pure-logic can cover without a network call:
extracting the mp4 asset URL from real page markup, and the fetch functions
going through ``csv_fetcher.http_get`` (monkeypatched) so a future TLS-gate
shift trips this stage in lockstep with the CSV/PDF health checks.
"""

from __future__ import annotations

import pytest

from pursue_index.av_fetch import client

# Real markup captured from the T48.5 probe (2026-08-09): dvidshub.net/video/1006056
# (VID) and dvidshub.net/video/1006119 (AUD) both carry this exact <source> shape.
_VID_PAGE_BODY = (
    '<source src="/video/1006056.m3u8" type="application/x-mpegURL" />'
    '                <source src="https://d34w7g4gy10iej.cloudfront.net/video/'
    '2605/DOD_111688723/DOD_111688723.mp4" type=\'video/mp4; codecs="avc1.42E01E, '
    'mp4a.40.2"\' />'
)
_AUD_PAGE_BODY = (
    '<source src="/video/1006119.m3u8" type="application/x-mpegURL" />'
    '                <source src="https://d34w7g4gy10iej.cloudfront.net/video/'
    '2605/DOD_111689232/DOD_111689232.mp4" type=\'video/mp4; codecs="avc1.42E01E, '
    'mp4a.40.2"\' />'
)
# The og:image/twitter:player meta tags also carry a DOD_<id> reference (a
# thumbnail JPEG under a different CloudFront host) — must NOT match.
_THUMBNAIL_ONLY_BODY = (
    '<meta property="og:image" content="https://d1ldvf68ux039x.cloudfront.net/'
    'thumbs/frames/video/2605/1006056/DOD_111688723.0000001/1000w_q95.jpg" />'
    '<source src="/video/1006056.m3u8" type="application/x-mpegURL" />'
)


_PAGE_URL = "https://www.dvidshub.net/video/1006056"
_ASSET_URL = (
    "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/"
    "DOD_111688723.mp4"
)
_MP4_HEAD = b"\x00\x00\x00\x1cftypM4V "


class _FakeResponse:
    """Stands in for the streamed transport response.

    ``chunks`` is handed out one piece at a time by :meth:`iter_content`,
    and ``chunks_yielded`` records how much of the body the caller actually
    pulled — that is what proves a body is read only as far as it is
    wanted.
    """

    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        content: bytes = b"",
        headers=None,
        chunks: list[bytes] | None = None,
        url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.url = url
        self._chunks = chunks if chunks is not None else ([content] if content else [])
        self.chunks_yielded = 0
        self.closed = False

    def iter_content(self, chunk_size: int = 8192):
        for chunk in self._chunks:
            self.chunks_yielded += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


# --- extract_dod_asset_url ---------------------------------------------


def test_extract_dod_asset_url_from_vid_page() -> None:
    url = client.extract_dod_asset_url(_VID_PAGE_BODY)
    assert url == (
        "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/"
        "DOD_111688723.mp4"
    )


def test_extract_dod_asset_url_from_aud_page() -> None:
    """AUD resolves via the exact same /video/<id> page shape as VID."""
    url = client.extract_dod_asset_url(_AUD_PAGE_BODY)
    assert url == (
        "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/"
        "DOD_111689232.mp4"
    )


def test_extract_dod_asset_url_ignores_thumbnail_meta_tags() -> None:
    """The og:image DOD_ reference is a .jpg outside a <source> tag — no match."""
    assert client.extract_dod_asset_url(_THUMBNAIL_ONLY_BODY) is None


def test_extract_dod_asset_url_no_source_tag() -> None:
    assert client.extract_dod_asset_url("<html><body>404</body></html>") is None


# --- extract_dod_id ------------------------------------------------------


def test_extract_dod_id_from_asset_url() -> None:
    assert (
        client.extract_dod_id(
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/"
            "DOD_111688723.mp4"
        )
        == "111688723"
    )


def test_extract_dod_id_none_when_absent() -> None:
    assert client.extract_dod_id("https://example.com/no-id-here.mp4") is None


# --- fetch_dvids_page ------------------------------------------------------


def test_fetch_dvids_page_uses_chrome_impersonation_and_video_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(200, text=_VID_PAGE_BODY)

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dvids_page("1006056")

    assert result == (200, _VID_PAGE_BODY)
    assert captured["url"] == "https://www.dvidshub.net/video/1006056"
    assert captured["impersonate"] == "chrome"


def test_fetch_dvids_page_returns_none_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        raise ConnectionError("boom")

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    assert client.fetch_dvids_page("1006056") is None


def test_fetch_dvids_page_propagates_non_200_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(404, text="not found")

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    assert client.fetch_dvids_page("9999999") == (404, "not found")


# --- fetch_dod_asset ------------------------------------------------------


def test_fetch_dod_asset_uses_chrome_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse(
            200,
            content=_MP4_HEAD,
            headers={"content-type": "binary/octet-stream"},
            url=_ASSET_URL,
        )

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dod_asset(_ASSET_URL, page_url=_PAGE_URL)

    assert result is not None
    assert (result.status_code, result.content_type, result.body) == (
        200, "binary/octet-stream", _MP4_HEAD,
    )
    assert result.error is None
    assert captured["url"] == _ASSET_URL
    assert captured["impersonate"] == "chrome"


def test_fetch_dod_asset_returns_none_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        raise TimeoutError("boom")

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    assert client.fetch_dod_asset(_ASSET_URL, page_url=_PAGE_URL) is None


# --- asset URL shape: absolute http(s), on the delivery host -------------


def test_check_asset_url_accepts_the_delivery_host_from_the_page() -> None:
    assert client.check_asset_url(_ASSET_URL, page_url=_PAGE_URL) is None


def test_check_asset_url_accepts_the_page_host_itself() -> None:
    """The page's own domain is a valid place for it to host its asset."""
    same_host = "https://www.dvidshub.net/assets/DOD_111688723.mp4"
    assert client.check_asset_url(same_host, page_url=_PAGE_URL) is None


def test_check_asset_url_requires_an_absolute_url() -> None:
    """A page-relative reference names no host, so it is not fetchable on
    its own terms and is reported rather than guessed at."""
    reason = client.check_asset_url(
        "/video/2605/DOD_111688723/DOD_111688723.mp4", page_url=_PAGE_URL
    )
    assert reason is not None
    assert "absolute" in reason


def test_check_asset_url_requires_an_http_scheme() -> None:
    """The stage fetches over HTTP; any other scheme is a different kind of
    reference than this stage knows how to retrieve."""
    reason = client.check_asset_url(
        "file:///tmp/DOD_111688723.mp4", page_url=_PAGE_URL
    )
    assert reason is not None
    assert "http" in reason


def test_check_asset_url_requires_an_expected_asset_host() -> None:
    """An asset is retrieved from the domain that serves the page or from
    the delivery network that page's media comes from — nowhere else."""
    reason = client.check_asset_url(
        "https://elsewhere.example/DOD_111688723.mp4", page_url=_PAGE_URL
    )
    assert reason is not None
    assert "host" in reason


def test_check_asset_url_host_match_is_not_a_substring_match() -> None:
    """A host is matched on whole labels, so a longer name that merely ends
    with the same characters is a different host."""
    reason = client.check_asset_url(
        "https://notcloudfront.net/DOD_111688723.mp4", page_url=_PAGE_URL
    )
    assert reason is not None


def test_fetch_dod_asset_reports_an_unexpected_requested_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check is applied at the transport seam too, so a direct caller
    gets the same guarantee as the stage."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        raise AssertionError("an off-host url is never requested")

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dod_asset(
        "https://elsewhere.example/DOD_1.mp4", page_url=_PAGE_URL
    )

    assert result is not None
    assert result.error is not None
    assert result.body == b""


def test_fetch_dod_asset_reports_a_final_url_off_the_expected_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The host expectation covers where the bytes actually came from, so a
    response that finished somewhere else is reported instead of staged."""

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(
            200,
            content=_MP4_HEAD,
            headers={"content-type": "binary/octet-stream"},
            url="https://elsewhere.example/DOD_1.mp4",
        )

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dod_asset(_ASSET_URL, page_url=_PAGE_URL)

    assert result is not None
    assert result.error is not None
    assert "host" in result.error
    assert result.body == b""


# --- byte ceiling, applied as the body arrives ---------------------------


def test_fetch_dod_asset_stops_reading_at_the_byte_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body is read only as far as the ceiling allows: once the limit is
    passed the read stops there, so the amount held in memory stays bounded
    by the ceiling however much more the response would have offered."""
    response = _FakeResponse(
        200,
        chunks=[b"x" * 10 for _ in range(100)],
        headers={"content-type": "binary/octet-stream"},
        url=_ASSET_URL,
    )

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return response

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dod_asset(_ASSET_URL, page_url=_PAGE_URL, max_bytes=25)

    assert result is not None
    assert result.error is not None
    assert "25" in result.error
    assert result.body == b""
    # The third 10-byte chunk is the first read that carries the total past
    # a 25-byte ceiling; the remaining 97 chunks are never pulled.
    assert response.chunks_yielded == 3


def test_fetch_dod_asset_accepts_a_body_at_the_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ceiling is a limit, not a margin: a body exactly that size is
    complete and is returned in full."""
    body = _MP4_HEAD + b"y" * 12

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(
            200,
            chunks=[body],
            headers={"content-type": "binary/octet-stream"},
            url=_ASSET_URL,
        )

    monkeypatch.setattr(client.csv_fetcher, "http_get", fake_get)

    result = client.fetch_dod_asset(
        _ASSET_URL, page_url=_PAGE_URL, max_bytes=len(body)
    )

    assert result is not None
    assert result.error is None
    assert result.body == body


def test_fetch_dod_asset_default_ceiling_clears_a_release_asset() -> None:
    """The default ceiling sits far above the size of a release A/V asset,
    so it bounds a single item without ever standing in the way of one."""
    assert client.MAX_ASSET_BYTES > 100 * 1024 * 1024
