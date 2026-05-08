"""PDF download stage.

Idempotent against the manifest: skips files that already exist with matching
size on disk. Uses tenacity for retries (PDFs are large; transient failures
are routine). Files are stored at ``settings.pdf_dir / card_id / filename``
so we can keep multiple revisions / future tranches isolated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pursue_index.config import settings
from pursue_index import get_logger
from pursue_index.scrape.types import CardMetadata, Manifest

log = get_logger(__name__)


def pdf_path_for(card: CardMetadata) -> Path:
    return settings.pdf_dir / card.card_id / card.pdf_filename


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
async def _download_one(client: httpx.AsyncClient, card: CardMetadata) -> Path:
    target = pdf_path_for(card)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and target.stat().st_size > 0:
        log.info("download.skip", card_id=card.card_id, path=str(target))
        return target

    log.info("download.start", card_id=card.card_id, url=str(card.pdf_url))
    async with client.stream("GET", str(card.pdf_url)) as resp:
        resp.raise_for_status()
        with target.open("wb") as fh:
            async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
    log.info("download.done", card_id=card.card_id, bytes=target.stat().st_size)
    return target


async def download_all(manifest: Manifest) -> list[Path]:
    """Download every PDF in the manifest with bounded concurrency."""
    sem = asyncio.Semaphore(settings.download_concurrency)
    results: list[Path] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, read=300.0),
        headers={"User-Agent": settings.scrape_user_agent},
        follow_redirects=True,
    ) as client:

        async def _bounded(card: CardMetadata) -> Path:
            async with sem:
                return await _download_one(client, card)

        results = await asyncio.gather(
            *(_bounded(c) for c in manifest.cards), return_exceptions=False
        )

    return results
