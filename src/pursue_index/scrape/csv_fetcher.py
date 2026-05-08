"""CSV-based scrape stage.

The PURSUE index page renders a CSV (``uap-csv.csv``) into a DataTables widget.
Rather than scraping the JS-rendered DOM, we fetch the underlying CSV directly.

Akamai gates the CSV on TLS fingerprint plus the full Chrome client-hint header
set; plain ``httpx``/``requests`` clients are 403'd. We use ``curl_cffi`` with
``impersonate="chrome"`` so the TLS handshake and HTTP/2 frame pattern look
identical to a real Chrome request. The ``_http_get`` indirection exists so
tests can monkeypatch a fake transport without touching the network.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import UTC, datetime
from typing import Any

from curl_cffi import requests as curl_requests

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.scrape.normalize import (
    clean_str,
    clean_title,
    filename_from_url,
    normalize_asset_type,
    parse_redacted,
    stable_card_id,
)
from pursue_index.scrape.types import CardMetadata, Manifest

log = get_logger(__name__)

# Chrome impersonation profile used by curl_cffi. ``chrome`` aliases to the
# latest stable Chrome fingerprint shipped with the curl_cffi version installed.
_IMPERSONATE = "chrome"


def _http_get(url: str, **kwargs: Any) -> Any:
    """Indirection seam over ``curl_cffi.requests.get`` for testability."""
    return curl_requests.get(url, **kwargs)


def fetch_raw_csv(url: str | None = None) -> bytes:
    """Download the CSV bytes from war.gov via Chrome-impersonated TLS."""
    target = url or str(settings.csv_url)
    log.info("scrape.csv.fetch", url=target)

    headers = {
        "Accept": "text/csv,application/csv,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.war.gov/UFO/",
    }
    if settings.scrape_user_agent:
        headers["User-Agent"] = settings.scrape_user_agent

    resp = _http_get(
        target,
        headers=headers,
        impersonate=_IMPERSONATE,
        timeout=30,
    )
    resp.raise_for_status()
    log.info("scrape.csv.fetched", bytes=len(resp.content))
    return resp.content


def parse_csv(raw: bytes) -> list[CardMetadata]:
    """Parse the CSV into a list of normalized CardMetadata."""
    text = raw.decode("utf-8-sig")  # CSV is UTF-8 with BOM
    reader = csv.DictReader(io.StringIO(text))

    cards: list[CardMetadata] = []
    skipped = 0

    for row in reader:
        # Drop trailing empty columns the CSV pads with
        clean_row = {k.strip(): v for k, v in row.items() if k and not k.startswith(" ")}

        try:
            card = _row_to_card(clean_row)
        except ValueError as exc:
            skipped += 1
            log.warning("scrape.row.skipped", reason=str(exc), title=clean_row.get("Title"))
            continue
        cards.append(card)

    log.info("scrape.parse.complete", cards=len(cards), skipped=skipped)
    return cards


def _row_to_card(row: dict[str, str]) -> CardMetadata:
    """Convert a single CSV row dict into a CardMetadata."""
    title = clean_title(row.get("Title"))
    if not title:
        raise ValueError("missing title")

    asset_type = normalize_asset_type(row.get("Type"))
    agency = clean_str(row.get("Agency")) or "(unknown)"
    asset_url = clean_str(row.get("PDF | Image Link"))
    modal_image_url = clean_str(row.get("Modal Image"))

    # Track everything the CSV gave us, including unknowns, in raw
    raw = {k: v for k, v in row.items() if k not in _MAPPED_KEYS}

    return CardMetadata(
        card_id=stable_card_id(asset_url, title),
        title=title,
        asset_type=asset_type,
        agency=agency,
        release_date=clean_str(row.get("Release Date")),
        incident_date=clean_str(row.get("Incident Date")),
        incident_location=clean_str(row.get("Incident Location")),
        redacted=parse_redacted(row.get("Redaction")),
        description=clean_str(row.get("Description Blurb")),
        asset_url=asset_url,
        asset_filename=filename_from_url(asset_url),
        modal_image_url=modal_image_url,
        dvids_video_id=clean_str(row.get("DVIDS Video ID")),
        video_title=clean_str(row.get("Video Title")),
        pdf_pairing=clean_str(row.get("PDF Pairing")),
        video_pairing=clean_str(row.get("Video Pairing")),
        raw=raw,
    )


_MAPPED_KEYS = {
    "Redaction",
    "Release Date",
    "Title",
    "Type",
    "Video Pairing",
    "PDF Pairing",
    "Description Blurb",
    "DVIDS Video ID",
    "Video Title",
    "Agency",
    "Incident Date",
    "Incident Location",
    "PDF | Image Link",
    "Modal Image",
}


def build_manifest(raw: bytes, cards: list[CardMetadata], source_url: str) -> Manifest:
    return Manifest(
        source_url=source_url,
        fetched_at=datetime.now(UTC),
        csv_sha256=hashlib.sha256(raw).hexdigest(),
        cards=cards,
    )


def run() -> Manifest:
    """End-to-end: fetch the CSV, parse it, build a manifest."""
    raw = fetch_raw_csv()
    cards = parse_csv(raw)
    return build_manifest(raw, cards, str(settings.csv_url))
