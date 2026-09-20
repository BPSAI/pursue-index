"""Fakes shared by the av-fetch fetch-stage tests: cards, DVIDS page bodies,
and the page/asset fetch seams."""

from __future__ import annotations

from dataclasses import dataclass

from pursue_index.av_fetch.client import AssetResponse


@dataclass
class FakeCard:
    card_id: str
    asset_type: str
    dvids_video_id: str | None


_VID_PAGE_BODY = (
    '<source src="/video/1006056.m3u8" type="application/x-mpegURL" />'
    '<source src="https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/'
    'DOD_111688723.mp4" type=\'video/mp4; codecs="avc1"\' />'
)
_AUD_PAGE_BODY = (
    '<source src="/video/1006119.m3u8" type="application/x-mpegURL" />'
    '<source src="https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/'
    'DOD_111689232.mp4" type=\'video/mp4; codecs="avc1"\' />'
)
_ASSET_BYTES = b"\x00\x00\x00\x1cftypM4V " + b"x" * 100


def _pages(mapping: dict[str, tuple[int, str] | None]):
    def _fetch(dvids_video_id: str):
        return mapping.get(dvids_video_id)

    return _fetch


def _assets(mapping: dict[str, tuple[int, str | None, bytes] | None]):
    """Asset-fetch seam: tuples in the mapping become AssetResponses.

    ``None`` still means a transport error. The seam takes ``page_url`` the
    way the real client does, so the stage's call shape is exercised.
    """

    def _fetch(url: str, **kwargs: object):
        found = mapping.get(url)
        if found is None:
            return None
        status, content_type, body = found
        return AssetResponse(status, content_type, body)

    return _fetch
