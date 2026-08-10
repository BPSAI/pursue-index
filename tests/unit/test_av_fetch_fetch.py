"""Tests for ``pursue_index.av_fetch.fetch`` — the direct-fetch stage.

Fully mocked HTTP (injected ``page_fetch``/``asset_fetch`` seams) per T48.5's
AC: no live network call in the suite. Covers both VID and AUD rows (DVIDS
serves AUD at ``/video/<id>`` too — asset_type never changes the URL), the
skip-and-count-never-silent failure contract, and the handoff to the existing
DOD-id matcher (``scripts/_video_ingest_core.match_cards_to_files``)
unchanged.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from pursue_index.av_fetch.client import AssetResponse
from pursue_index.av_fetch.fetch import AVFetchReport, fetch_one, fetch_worklist

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


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


# --- fetch_one: happy path ------------------------------------------------


def test_fetch_one_vid_writes_dod_named_file(tmp_path: Path) -> None:
    card = FakeCard("c1", "VID", "1006056")
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY)})
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            )
        }
    )

    item = fetch_one(card, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert item.status == "fetched"
    assert item.path == tmp_path / "DOD_111688723.mp4"
    assert item.path.read_bytes() == _ASSET_BYTES
    assert item.byte_size == len(_ASSET_BYTES)
    assert item.content_type == "binary/octet-stream"


def test_fetch_one_aud_resolves_via_video_path(tmp_path: Path) -> None:
    """AUD asset_type still hits /video/<id> — never /audio/<id>."""
    card = FakeCard("c2", "AUD", "1006119")
    page_fetch = _pages({"1006119": (200, _AUD_PAGE_BODY)})
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/DOD_111689232.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            )
        }
    )

    item = fetch_one(card, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert item.status == "fetched"
    assert item.path == tmp_path / "DOD_111689232.mp4"
    assert item.asset_type == "AUD"


def test_fetch_one_skips_existing_nonempty_file(tmp_path: Path) -> None:
    existing = tmp_path / "DOD_111688723.mp4"
    existing.write_bytes(b"already here")
    card = FakeCard("c1", "VID", "1006056")
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY)})

    def _asset_fetch_should_not_be_called(url: str):
        raise AssertionError("asset_fetch must not be called when file exists")

    item = fetch_one(
        card, tmp_path, page_fetch=page_fetch, asset_fetch=_asset_fetch_should_not_be_called
    )

    assert item.status == "skipped_existing"
    assert item.path == existing


# --- fetch_one: failure modes (skip-and-count, never silent) -------------


def test_fetch_one_fails_on_invalid_dvids_id(tmp_path: Path) -> None:
    card = FakeCard("c3", "VID", None)
    item = fetch_one(card, tmp_path, page_fetch=_pages({}), asset_fetch=_assets({}))
    assert item.status == "failed"
    assert item.error


def test_fetch_one_fails_on_page_transport_error(tmp_path: Path) -> None:
    card = FakeCard("c4", "VID", "9999999")
    item = fetch_one(
        card, tmp_path, page_fetch=_pages({"9999999": None}), asset_fetch=_assets({})
    )
    assert item.status == "failed"
    assert "transport" in item.error


def test_fetch_one_fails_on_page_404(tmp_path: Path) -> None:
    card = FakeCard("c5", "VID", "8888888")
    item = fetch_one(
        card,
        tmp_path,
        page_fetch=_pages({"8888888": (404, "not found")}),
        asset_fetch=_assets({}),
    )
    assert item.status == "failed"
    assert "404" in item.error


def test_fetch_one_fails_when_no_dod_url_on_page(tmp_path: Path) -> None:
    card = FakeCard("c6", "VID", "1006056")
    item = fetch_one(
        card,
        tmp_path,
        page_fetch=_pages({"1006056": (200, "<html>no source here</html>")}),
        asset_fetch=_assets({}),
    )
    assert item.status == "failed"
    assert "no DOD asset url" in item.error


def test_fetch_one_fails_on_non_video_content_type(tmp_path: Path) -> None:
    """A CDN block that still returns 200 with an HTML body must not be staged."""
    card = FakeCard("c7", "VID", "1006056")
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY)})
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "text/html",
                b"<html>blocked</html>",
            )
        }
    )
    item = fetch_one(card, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)
    assert item.status == "failed"
    assert "content-type" in item.error
    assert not (tmp_path / "DOD_111688723.mp4").exists()


def test_fetch_one_fails_on_empty_body(tmp_path: Path) -> None:
    card = FakeCard("c8", "VID", "1006056")
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY)})
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "binary/octet-stream",
                b"",
            )
        }
    )
    item = fetch_one(card, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)
    assert item.status == "failed"


# --- the asset reference on the page must be one this stage can act on ---


def _page_with_src(src: str) -> str:
    return (
        '<source src="/video/1006056.m3u8" type="application/x-mpegURL" />'
        f'<source src="{src}" type=\'video/mp4; codecs="avc1"\' />'
    )


def _asset_fetch_never_called(url: str, **kwargs: object):
    raise AssertionError("an unusable asset reference is never fetched")


def _item_for_src(tmp_path: Path, src: str):
    card = FakeCard("c9", "VID", "1006056")
    return fetch_one(
        card,
        tmp_path,
        page_fetch=_pages({"1006056": (200, _page_with_src(src))}),
        asset_fetch=_asset_fetch_never_called,
    )


def test_fetch_one_fails_on_relative_asset_reference(tmp_path: Path) -> None:
    """A page-relative reference names no host, so the item is reported
    rather than fetched from a guessed-at location."""
    item = _item_for_src(tmp_path, "/video/2605/DOD_111688723/DOD_111688723.mp4")
    assert item.status == "failed"
    assert "absolute" in item.error


def test_fetch_one_fails_on_non_http_asset_reference(tmp_path: Path) -> None:
    """This stage retrieves over HTTP; another scheme is a different kind of
    reference than it knows how to fetch."""
    item = _item_for_src(tmp_path, "file:///tmp/DOD_111688723.mp4")
    assert item.status == "failed"
    assert "http" in item.error


def test_fetch_one_fails_on_asset_reference_off_the_expected_host(
    tmp_path: Path,
) -> None:
    """An asset comes from the domain serving the page or from that page's
    delivery network — a reference to anywhere else is reported."""
    item = _item_for_src(tmp_path, "https://elsewhere.example/DOD_111688723.mp4")
    assert item.status == "failed"
    assert "host" in item.error


def test_unusable_asset_reference_is_a_shortfall(tmp_path: Path) -> None:
    """An item skipped for its reference still counts, so the run exits
    non-zero rather than reporting a quietly short set."""
    cards = [FakeCard("c9", "VID", "1006056")]
    report = fetch_worklist(
        cards,
        tmp_path,
        page_fetch=_pages(
            {"1006056": (200, _page_with_src("https://elsewhere.example/DOD_111688723.mp4"))}
        ),
        asset_fetch=_asset_fetch_never_called,
    )
    assert report.failed == 1
    assert report.ok is False


# --- staged bytes are the media type the response claims ----------------


def _fetch_with_body(tmp_path: Path, body: bytes, content_type: str = "binary/octet-stream"):
    card = FakeCard("c1", "VID", "1006056")
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/"
            "DOD_111688723.mp4": (200, content_type, body)
        }
    )
    return fetch_one(
        card,
        tmp_path,
        page_fetch=_pages({"1006056": (200, _VID_PAGE_BODY)}),
        asset_fetch=asset_fetch,
    )


def test_fetch_one_stages_bytes_carrying_the_mp4_box_marker(tmp_path: Path) -> None:
    """An MP4 opens with an ``ftyp`` box, so a body that carries one is the
    media type the stage set out to collect and is staged."""
    item = _fetch_with_body(tmp_path, _ASSET_BYTES)
    assert item.status == "fetched"
    assert (tmp_path / "DOD_111688723.mp4").exists()


def test_fetch_one_fails_when_body_is_not_an_mp4(tmp_path: Path) -> None:
    """A body served under a generic content type is checked against the
    MP4 box marker before it is staged, so what lands in the staging dir is
    the media type the matcher downstream expects."""
    item = _fetch_with_body(tmp_path, b"GIF89a" + b"x" * 100)
    assert item.status == "failed"
    assert "mp4" in item.error.lower()
    assert not (tmp_path / "DOD_111688723.mp4").exists()


def test_fetch_one_fails_when_body_is_too_short_to_identify(tmp_path: Path) -> None:
    """A body too short to carry a box header is not an MP4."""
    item = _fetch_with_body(tmp_path, b"\x00\x00")
    assert item.status == "failed"
    assert not (tmp_path / "DOD_111688723.mp4").exists()


def test_fetch_one_reports_the_reason_the_client_gives(tmp_path: Path) -> None:
    """When the client declines a response — a body past the byte ceiling,
    say — the stage reports that stated reason as this item's failure."""
    card = FakeCard("c1", "VID", "1006056")

    def asset_fetch(url: str, **kwargs: object):
        return AssetResponse(
            200, "binary/octet-stream", b"",
            error="asset body is larger than the 2147483648 byte ceiling",
        )

    item = fetch_one(
        card,
        tmp_path,
        page_fetch=_pages({"1006056": (200, _VID_PAGE_BODY)}),
        asset_fetch=asset_fetch,
    )

    assert item.status == "failed"
    assert "ceiling" in item.error
    assert not (tmp_path / "DOD_111688723.mp4").exists()


def test_oversized_asset_is_a_shortfall(tmp_path: Path) -> None:
    """A body past the ceiling is a per-item skip that still counts, so the
    run exits non-zero on the shortfall."""

    def asset_fetch(url: str, **kwargs: object):
        return AssetResponse(
            200, "binary/octet-stream", b"", error="asset body is larger than the ceiling"
        )

    report = fetch_worklist(
        [FakeCard("c1", "VID", "1006056")],
        tmp_path,
        page_fetch=_pages({"1006056": (200, _VID_PAGE_BODY)}),
        asset_fetch=asset_fetch,
    )

    assert report.failed == 1
    assert report.ok is False


def test_fetch_one_passes_the_page_url_to_the_asset_fetch(tmp_path: Path) -> None:
    """The stage tells the client which page the reference came from, so the
    host expectation is derived from that page rather than assumed."""
    captured: dict[str, object] = {}

    def asset_fetch(url: str, **kwargs: object):
        captured.update(kwargs)
        return AssetResponse(200, "binary/octet-stream", _ASSET_BYTES)

    fetch_one(
        FakeCard("c1", "VID", "1006056"),
        tmp_path,
        page_fetch=_pages({"1006056": (200, _VID_PAGE_BODY)}),
        asset_fetch=asset_fetch,
    )

    assert captured["page_url"] == "https://www.dvidshub.net/video/1006056"


# --- fetch_worklist: skip-and-count, shortfall never silent ---------------


def test_fetch_worklist_counts_fetched_skipped_failed(tmp_path: Path) -> None:
    cards = [
        FakeCard("ok", "VID", "1006056"),
        FakeCard("bad", "VID", "9999999"),
    ]
    page_fetch = _pages(
        {"1006056": (200, _VID_PAGE_BODY), "9999999": None}
    )
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            )
        }
    )

    report = fetch_worklist(cards, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert isinstance(report, AVFetchReport)
    assert report.fetched == 1
    assert report.skipped == 0
    assert report.failed == 1
    assert report.ok is False  # one failure -> shortfall, never silent


def test_fetch_worklist_ok_true_when_no_failures(tmp_path: Path) -> None:
    cards = [FakeCard("ok", "VID", "1006056")]
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY)})
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            )
        }
    )

    report = fetch_worklist(cards, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert report.ok is True


def test_fetch_worklist_continues_past_a_failed_item(tmp_path: Path) -> None:
    """One bad item must not abort the run — the rest still get fetched."""
    cards = [
        FakeCard("bad", "VID", "9999999"),
        FakeCard("ok", "AUD", "1006119"),
    ]
    page_fetch = _pages(
        {"9999999": None, "1006119": (200, _AUD_PAGE_BODY)}
    )
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/DOD_111689232.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            )
        }
    )

    report = fetch_worklist(cards, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert report.failed == 1
    assert report.fetched == 1


# --- integration: hand off to the existing DOD-id matcher, unchanged -----


def test_fetch_worklist_output_consumed_unchanged_by_existing_matcher(
    tmp_path: Path,
) -> None:
    """The staging dir fetch_worklist writes is exactly what
    ``scripts/_video_ingest_core.match_cards_to_files`` (the DOD-id matcher
    ``ingest_release_videos.py --desktop`` already runs) expects — same
    ``DOD_<id>.mp4`` filename convention, no changes to the matcher."""
    import _video_ingest_core as core  # see sys.path setup above

    @dataclass
    class ManifestCard:
        card_id: str
        asset_type: str
        dvids_video_id: str | None

    cards = [
        ManifestCard("card-vid", "VID", "1006056"),
        ManifestCard("card-aud", "AUD", "1006119"),
    ]
    page_fetch = _pages(
        {"1006056": (200, _VID_PAGE_BODY), "1006119": (200, _AUD_PAGE_BODY)}
    )
    asset_fetch = _assets(
        {
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES,
            ),
            "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/DOD_111689232.mp4": (
                200,
                "binary/octet-stream",
                _ASSET_BYTES + b"y",
            ),
        }
    )

    report = fetch_worklist(cards, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)
    assert report.ok is True

    staged_files = sorted(tmp_path.glob("*.mp4"))

    # The matcher re-derives the DOD filename per card via its own resolver
    # (network scrape in production; here a fixture stand-in mirroring what
    # the DVIDS page actually contains) — proving fetch_worklist's output is
    # consumed with ZERO changes to match_cards_to_files itself.
    def dod_resolver(card: ManifestCard) -> str | None:
        return {
            "card-vid": "DOD_111688723.mp4",
            "card-aud": "DOD_111689232.mp4",
        }.get(card.card_id)

    matched, unmatched_cards, unmatched_files = core.match_cards_to_files(
        cards, staged_files, dod_resolver
    )

    assert set(matched.keys()) == {"card-vid", "card-aud"}
    assert matched["card-vid"][1] == tmp_path / "DOD_111688723.mp4"
    assert matched["card-aud"][1] == tmp_path / "DOD_111689232.mp4"
    assert unmatched_cards == []
    assert unmatched_files == []
