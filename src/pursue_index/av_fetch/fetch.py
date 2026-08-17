"""Fetch stage: DOD id -> file URL -> staged bytes for the existing DOD-id matcher.

Per card: resolve the DVIDS page, extract the direct DOD asset URL, GET the
bytes, and write ``<staging_dir>/DOD_<id>.mp4`` — the exact filename
convention ``scripts/_video_ingest_core.match_cards_to_files`` (the matcher
``ingest_release_videos.py --desktop`` already runs) expects.

A fetched asset is bounded and checked to be the media type it claims
before anything reaches the staging dir. The asset reference taken off the
page must be an absolute http(s) URL on a host the page is expected to
serve media from; the body is read against a byte ceiling as it arrives;
and the bytes must open with the MP4 box marker as well as carry an
expected content-type. Each of those is a per-item skip-and-count, so what
the matcher downstream picks up is known-good and a shortfall still exits
non-zero. That matcher is never touched by this module; it re-derives the
filename per card through its own resolver, so fetch_worklist's output is
consumed unchanged.

Fetch failures are per-item skip-and-count, never silent: one bad card does
not abort the run, but ``AVFetchReport.ok`` is False whenever anything failed
so the caller can exit non-zero on a shortfall.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pursue_index import get_logger
from pursue_index.av_fetch import client

log = get_logger(__name__)

PageFetch = Callable[[str], "tuple[int, str] | None"]
AssetFetch = Callable[..., "client.AssetResponse | None"]

# Content-types the direct asset GET is expected to return. A CDN block that
# still answers 200 typically serves an HTML error page instead — that must
# fail the item rather than be staged as a video.
_VIDEO_CONTENT_TYPES = ("video/", "application/octet-stream", "binary/octet-stream")

# An MP4 file opens with a box header: a four-byte big-endian length
# followed by the box type, and the first box is ``ftyp``. The delivery host
# serves these assets under a generic binary content-type, so the bytes are
# checked against this marker before anything is staged — what lands in the
# staging dir is then known to be the media type the downstream DOD-id
# matcher expects, not merely something that arrived with a 200.
_MP4_FTYP_OFFSET = 4
_MP4_FTYP_MARKER = b"ftyp"


@dataclass
class AVFetchItem:
    """Outcome of fetching one card's A/V bytes."""

    card_id: str
    dvids_video_id: str | None
    asset_type: str
    status: str  # "fetched" | "skipped_existing" | "failed"
    path: Path | None = None
    byte_size: int | None = None
    content_type: str | None = None
    error: str | None = None


@dataclass
class AVFetchReport:
    """Per-item results plus the shortfall gate."""

    items: list[AVFetchItem] = field(default_factory=list)

    @property
    def fetched(self) -> int:
        return sum(1 for i in self.items if i.status == "fetched")

    @property
    def skipped(self) -> int:
        return sum(1 for i in self.items if i.status == "skipped_existing")

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if i.status == "failed")

    @property
    def ok(self) -> bool:
        """True iff no per-item failures — the shortfall gate a CLI exits on."""
        return self.failed == 0


def _is_valid_dvids_id(value: str | None) -> bool:
    """True iff ``value`` is a bare numeric DVIDS id (safe to URL-interpolate)."""
    return value is not None and value.isdigit()


def _looks_like_video(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower().startswith(_VIDEO_CONTENT_TYPES)


def _looks_like_mp4(body: bytes) -> bool:
    """True iff ``body`` opens with an MP4 ``ftyp`` box header."""
    end = _MP4_FTYP_OFFSET + len(_MP4_FTYP_MARKER)
    return len(body) >= end and body[_MP4_FTYP_OFFSET:end] == _MP4_FTYP_MARKER


def _dest_path(staging_dir: Path, dod_id: str) -> Path:
    return staging_dir / f"DOD_{dod_id}.mp4"


def _write_staged(dest: Path, body: bytes) -> None:
    """Write ``body`` to ``dest`` atomically (temp file + rename)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)


def _resolve_asset_url(
    card_id: str, dvids_id: str, asset_type: str, page_fetch: PageFetch
) -> tuple[str, str] | AVFetchItem:
    """Return ``(asset_url, dod_id)`` or a failed :class:`AVFetchItem`."""
    page = page_fetch(dvids_id)
    if page is None:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error="dvids page fetch: transport error",
        )
    status, body = page
    if status != 200:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error=f"dvids page fetch: HTTP {status}",
        )
    asset_url = client.extract_dod_asset_url(body)
    if not asset_url:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error="no DOD asset url found on page",
        )
    unusable = client.check_asset_url(asset_url, page_url=client.dvids_page_url(dvids_id))
    if unusable:
        return AVFetchItem(card_id, dvids_id, asset_type, "failed", error=unusable)
    dod_id = client.extract_dod_id(asset_url)
    if not dod_id:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error="could not parse DOD id from asset url",
        )
    return asset_url, dod_id


def _fetch_and_stage(
    card_id: str,
    dvids_id: str,
    asset_type: str,
    asset_url: str,
    dest: Path,
    asset_fetch: AssetFetch,
) -> AVFetchItem:
    """GET ``asset_url``, verify it, and write ``dest`` — or return a failure.

    The bytes are staged only once they are bounded, arrived from an
    expected asset host, carry an expected content-type, and open with the
    MP4 box marker.
    """
    fetched = asset_fetch(asset_url, page_url=client.dvids_page_url(dvids_id))
    if fetched is None:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error="asset fetch: transport error",
        )
    if fetched.error:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error=f"asset fetch: {fetched.error}",
        )
    asset_status, content_type, body = (
        fetched.status_code, fetched.content_type, fetched.body
    )
    if asset_status != 200:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error=f"asset fetch: HTTP {asset_status}",
        )
    if not body:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed", error="asset fetch: empty body"
        )
    if not _looks_like_video(content_type):
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error=f"asset fetch: unexpected content-type {content_type!r}",
        )
    if not _looks_like_mp4(body):
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed",
            error="asset fetch: body does not open with an mp4 ftyp box",
        )

    _write_staged(dest, body)
    log.info(
        "av_fetch.item.fetched", card_id=card_id, dvids_video_id=dvids_id, bytes=len(body)
    )
    return AVFetchItem(
        card_id, dvids_id, asset_type, "fetched",
        path=dest, byte_size=len(body), content_type=content_type,
    )


def fetch_one(
    card: Any,
    staging_dir: Path,
    *,
    page_fetch: PageFetch,
    asset_fetch: AssetFetch,
) -> AVFetchItem:
    """Fetch one card's A/V bytes into ``staging_dir``. Never raises."""
    card_id = card.card_id
    dvids_id = card.dvids_video_id
    asset_type = card.asset_type

    if not _is_valid_dvids_id(dvids_id):
        return AVFetchItem(
            card_id, dvids_id, asset_type, "failed", error="invalid dvids_video_id"
        )

    resolved = _resolve_asset_url(card_id, dvids_id, asset_type, page_fetch)
    if isinstance(resolved, AVFetchItem):
        return resolved
    asset_url, dod_id = resolved

    dest = _dest_path(staging_dir, dod_id)
    if dest.exists() and dest.stat().st_size > 0:
        return AVFetchItem(
            card_id, dvids_id, asset_type, "skipped_existing",
            path=dest, byte_size=dest.stat().st_size,
        )

    return _fetch_and_stage(card_id, dvids_id, asset_type, asset_url, dest, asset_fetch)


def fetch_worklist(
    cards: list[Any],
    staging_dir: Path,
    *,
    page_fetch: PageFetch = client.fetch_dvids_page,
    asset_fetch: AssetFetch = client.fetch_dod_asset,
) -> AVFetchReport:
    """Fetch every card's A/V bytes into ``staging_dir``. Skip-and-count only —
    one item's failure never aborts the rest."""
    items = [
        fetch_one(c, staging_dir, page_fetch=page_fetch, asset_fetch=asset_fetch)
        for c in cards
    ]
    report = AVFetchReport(items=items)
    log.info(
        "av_fetch.summary",
        fetched=report.fetched, skipped=report.skipped, failed=report.failed,
        total=len(items),
    )
    return report
