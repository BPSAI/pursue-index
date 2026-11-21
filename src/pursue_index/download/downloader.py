"""Asset download stage.

Idempotent against the manifest: skips files that already exist with non-zero
size, except for cards named in ``refresh_shas`` (``bytes-changed`` cards):
those are re-fetched to a temporary file, checked against the registry's
latest sha, and only then replace the file. Routes by ``asset_type``:

  * PDF → ``settings.pdf_dir / {card_id} / {filename}``
  * IMG → ``settings.image_dir / {card_id} / {filename}``
  * VID → DVIDS-hosted; only fetched when ``settings.download_videos`` is set,
          since they require a separate API + are large. For now we just record
          the metadata we already have on the card.

Cards without an ``asset_url`` are skipped with a warning.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.scrape.types import CardMetadata, Manifest

log = get_logger(__name__)

# Asset bytes are only ever served from the official DoW host. Validate the
# asset_url scheme + host before fetching so a compromised/spoofed upstream CSV
# (or a tampered asset_url on an otherwise operator-approved tranche) can't turn
# the download fan-out into an SSRF / arbitrary-fetch primitive — the
# `ingest run --from-diff` path automates this fetch behind an approval gate
# that attests tranche legitimacy, not per-URL safety.
_ALLOWED_ASSET_SCHEMES = frozenset({"https"})
_ALLOWED_ASSET_HOSTS = frozenset({"www.war.gov", "war.gov"})


class DownloadShaMismatchError(RuntimeError):
    """A re-fetched file's sha differs from the registry's latest; the old file is kept."""


def _is_allowed_asset_url(url: str) -> bool:
    """True iff ``url`` is an https URL on the official-host allowlist.

    Uses ``hostname`` (lowercased, no userinfo/port) for an exact host match,
    so suffix-spoofs like ``www.war.gov.evil.com`` are rejected.
    """
    parsed = urlparse(url)
    return (
        parsed.scheme in _ALLOWED_ASSET_SCHEMES
        and parsed.hostname in _ALLOWED_ASSET_HOSTS
    )


def asset_path_for(card: CardMetadata) -> Path | None:
    """Return the on-disk path the downloader should write this asset
    to, or None if the card has no downloadable bytes.

    None paths:
      * No ``asset_url`` (VID + AUD cards are DVIDS-hosted and have
        null asset_url today).
      * No ``asset_filename``.
      * Unknown ``asset_type`` (AUD without a configured download
        target). ``.get()`` instead of ``[]`` so a future
        asset type that lands upstream without a corresponding
        settings entry fails-closed (skipped) rather than KeyErroring
        through the pipeline.
    """
    if not card.asset_url or not card.asset_filename:
        return None
    base = {
        "PDF": settings.pdf_dir,
        "IMG": settings.image_dir,
        "VID": settings.video_dir,
    }.get(card.asset_type)
    if base is None:
        return None
    return base / card.card_id / card.asset_filename


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_not_exception_type(DownloadShaMismatchError),
)
async def _download_one(
    client: httpx.AsyncClient, card: CardMetadata, *, expected_sha: str | None = None
) -> Path | None:
    """Fetch one card's asset. ``expected_sha`` marks a refresh: re-fetch even if
    the file exists, and replace it only when the fetched bytes hash to it."""
    target = asset_path_for(card)
    if target is None:
        log.warning("download.skip.no_url", card_id=card.card_id, title=card.title)
        return None

    if card.asset_type == "VID" and not settings.download_videos:
        log.info("download.skip.video", card_id=card.card_id)
        return None

    target.parent.mkdir(parents=True, exist_ok=True)

    if expected_sha is None and target.exists() and target.stat().st_size > 0:
        log.info("download.skip.exists", card_id=card.card_id, path=str(target))
        return target

    if not _is_allowed_asset_url(str(card.asset_url)):
        # Skip (don't raise — @retry would just hammer it) an off-allowlist URL.
        log.warning(
            "download.skip.disallowed_url",
            card_id=card.card_id,
            url=str(card.asset_url),
        )
        return None

    log.info(
        "download.start",
        card_id=card.card_id,
        type=card.asset_type,
        url=str(card.asset_url),
    )
    # Write beside the target, so the final replace stays on one filesystem.
    tmp = target.with_name(f".{target.name}.part")
    digest = hashlib.sha256()
    try:
        async with client.stream("GET", str(card.asset_url)) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                    digest.update(chunk)
                    fh.write(chunk)
        if expected_sha is not None and digest.hexdigest() != expected_sha:
            raise DownloadShaMismatchError(
                f"card {card.card_id}: re-fetched sha {digest.hexdigest()} != registry "
                f"latest {expected_sha}; kept the existing file"
            )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("download.done", card_id=card.card_id, bytes=target.stat().st_size)
    return target


async def download_all(
    manifest: Manifest, refresh_shas: dict[str, str] | None = None
) -> list[Path | None]:
    """Download every asset in the manifest with bounded concurrency.

    ``refresh_shas`` maps ``bytes-changed`` card_ids to the registry's latest sha;
    those cards are re-fetched and verified even when a local file exists.
    """
    refresh_shas = refresh_shas or {}
    sem = asyncio.Semaphore(settings.download_concurrency)
    headers = {
        "User-Agent": settings.scrape_user_agent
        or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.war.gov/UFO/",
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, read=300.0),
        headers=headers,
        follow_redirects=True,
    ) as client:

        async def _bounded(card: CardMetadata) -> Path | None:
            async with sem:
                return await _download_one(
                    client, card, expected_sha=refresh_shas.get(card.card_id)
                )

        results = await asyncio.gather(
            *(_bounded(c) for c in manifest.cards), return_exceptions=False
        )

    downloaded = sum(1 for r in results if r is not None)
    log.info("download.summary", downloaded=downloaded, total=len(manifest.cards))
    return results
