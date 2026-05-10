"""PDF-fetch health check for the 6h cron.

The CSV poll catches Akamai gating shifts on the index endpoint, but
PDF downloads live behind a separate path (``war.gov/medialink/ufo/...``).
Akamai *could* tighten one without touching the other, and we'd find
out hours/days late from a download stage failure.

This module pings a single, deterministically-selected sentinel PDF
from the latest manifest using the **same** curl_cffi Chrome-impersonate
machinery the CSV fetcher uses (``csv_fetcher._http_get``). Re-using
the indirection keeps both surveillance lanes aligned: any TLS or
header contract change shows up in both at once.

Sentinel rule: the lex-smallest ``card_id`` among PDF cards. Stable
across manifest reorderings, deterministic across runs, and produces
reproducible failures the operator can grep.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index import get_logger
from pursue_index.scrape import csv_fetcher

log = get_logger(__name__)

# Re-use the CSV fetcher's Chrome impersonation profile. If Akamai
# changes the TLS gate, both health checks fail in lockstep — that's
# the whole point of sharing this constant.
_IMPERSONATE = "chrome"

# Range request keeps the health check cheap. We only need to confirm
# the gate opens; we don't need the full PDF body.
_RANGE_HEADER = "bytes=0-1023"


@dataclass(frozen=True)
class Sentinel:
    """A single PDF card chosen for health-checking.

    Frozen so the workflow log can quote it verbatim without worry
    about a downstream caller mutating fields.
    """

    card_id: str
    asset_type: str
    asset_url: str


@dataclass(frozen=True)
class HealthOk:
    """Successful health check."""

    url: str
    bytes_received: int


@dataclass(frozen=True)
class HealthFail:
    """Failed health check.

    ``status`` is the HTTP status (or ``-1`` for transport errors so the
    log line stays a simple key=value pair). ``error`` is a short
    human-readable string suitable for an issue body.
    """

    url: str
    status: int
    error: str


def check_pdf_health(url: str) -> HealthOk | HealthFail:
    """Fetch the first 1 KiB of ``url`` and return ok/fail.

    Goes through ``csv_fetcher._http_get`` so the curl_cffi Chrome
    impersonation contract is exercised in lockstep with CSV fetches.
    Tests monkeypatch ``_http_get`` to skip the network.

    Range request bounds the cost: we only need to know the gate
    opens, not the full file body.
    """
    headers = {"Range": _RANGE_HEADER}
    try:
        resp = csv_fetcher._http_get(
            url,
            headers=headers,
            impersonate=_IMPERSONATE,
            timeout=30,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — surface any transport failure
        log.warning("pdf_health.transport_error", url=url, exc_type=type(exc).__name__)
        return HealthFail(url=url, status=-1, error=f"{type(exc).__name__}: {exc}")

    status = int(getattr(resp, "status_code", 0))
    # Range responses are 206; full 200s are also fine. Anything else is a fail.
    if status in (200, 206):
        body = getattr(resp, "content", b"") or b""
        log.info("pdf_health.ok", url=url, bytes=len(body), status=status)
        return HealthOk(url=url, bytes_received=len(body))

    log.warning("pdf_health.http_error", url=url, status=status)
    return HealthFail(url=url, status=status, error=f"HTTP {status}")


def pick_sentinel(manifest_path: Path) -> Sentinel:
    """Choose a deterministic sentinel PDF from the manifest.

    Reads ``manifest_path`` as raw JSON (not the pydantic model) so the
    health check stays robust to schema drift — we only need card_id,
    asset_type, asset_url.
    """
    data = json.loads(manifest_path.read_text())
    cards: list[dict[str, Any]] = data.get("cards", [])
    pdfs = [c for c in cards if c.get("asset_type") == "PDF" and c.get("asset_url")]
    if not pdfs:
        raise ValueError("no PDF cards in manifest — cannot pick sentinel")

    pdfs.sort(key=lambda c: c["card_id"])
    chosen = pdfs[0]
    return Sentinel(
        card_id=chosen["card_id"],
        asset_type=chosen["asset_type"],
        asset_url=chosen["asset_url"],
    )
