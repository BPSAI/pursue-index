"""Asset download stage.

Idempotent against the manifest: skips files that already exist with non-zero
size, except for cards named in ``refresh_shas`` (``bytes-changed`` cards):
those are re-fetched to a temporary file, checked against the registry's
latest sha, and only then replace the file. A card whose bytes fail that check
keeps its old file; the rest of the batch finishes, then ``DownloadBatchError``
names the failed cards. A PDF fetched for the first time is checked the same way
against the registry's latest row for its card, when one exists, and the bytes are
dropped on a mismatch. Every per-card error (network, HTTP status, write, sha)
joins that one aggregation; one bad card never aborts the gather. Routes by
``asset_type``:

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
from tenacity import (
    RetryError,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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


class DownloadBatchError(RuntimeError):
    """Some cards failed verification; every other card was still processed.

    ``failed`` maps each failed card_id to the reason; their old files are kept.
    """

    def __init__(self, failed: dict[str, str]) -> None:
        self.failed = dict(failed)
        lines = "".join(f"\n  {card_id}: {why}" for card_id, why in self.failed.items())
        super().__init__(f"{len(self.failed)} card(s) failed verification:{lines}")


def _is_allowed_asset_url(url: str) -> bool:
    """True iff ``url`` is an https URL on the official-host allowlist.

    Uses ``hostname`` (lowercased, no userinfo/port) for an exact host match,
    so suffix-spoofs like ``www.war.gov.evil.com`` are rejected.
    """
    parsed = urlparse(url)
    return parsed.scheme in _ALLOWED_ASSET_SCHEMES and parsed.hostname in _ALLOWED_ASSET_HOSTS


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
    client: httpx.AsyncClient,
    card: CardMetadata,
    *,
    expected_sha: str | None = None,
    registry_sha: str | None = None,
    accept_shas: frozenset[str] = frozenset(),
    outcomes: dict[str, str] | None = None,
) -> Path | None:
    """Fetch one card's asset. ``expected_sha`` marks a refresh: re-fetch even if
    the file exists, and replace it only when the fetched bytes hash to it.
    ``registry_sha`` (the registry's latest row, when one exists) is checked the
    same way on a first download; an existing file is still skipped. ``accept_shas``
    are the new shas a reviewed ``resave-content-verified`` disposition covers for
    that registry row: fetching one is accepted and recorded in ``outcomes``."""
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
    fetched = await _fetch_verified(
        client, card, target, expected_sha or registry_sha, bool(expected_sha), accept_shas
    )
    required = expected_sha or registry_sha
    if outcomes is not None and required is not None and fetched != required:
        outcomes[card.card_id] = DISPOSITIONED_RESAVE
        log.warning("download.dispositioned_resave", card_id=card.card_id, sha=fetched)
    log.info("download.done", card_id=card.card_id, bytes=target.stat().st_size)
    return target


async def _fetch_verified(
    client: httpx.AsyncClient,
    card: CardMetadata,
    target: Path,
    required_sha: str | None,
    is_refresh: bool,
    accept_shas: frozenset[str] = frozenset(),
) -> str:
    """Stream the card's URL beside ``target`` and replace it only if the sha is acceptable."""
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
        got = digest.hexdigest()
        if required_sha is not None and got != required_sha and got not in accept_shas:
            kept = "kept the existing file" if is_refresh else "did not keep the download"
            raise DownloadShaMismatchError(
                f"card {card.card_id}: fetched sha {got} != registry latest {required_sha}; "
                f"{kept}. If upstream legitimately re-saved this file, review the change and "
                f"append a resave-content-verified row for ({card.card_id}, {got}) with "
                f"old_sha256 {required_sha} to data/byte-change-dispositions.jsonl, then "
                "re-run; otherwise the registry or the upstream file is wrong."
            )
        os.replace(tmp, target)
        return got
    finally:
        tmp.unlink(missing_ok=True)


def _failure_reason(exc: BaseException) -> str:
    """The underlying error of a retried call, as ``Type: message``."""
    if isinstance(exc, RetryError) and exc.last_attempt.exception() is not None:
        exc = exc.last_attempt.exception()  # type: ignore[assignment]
    return f"{type(exc).__name__}: {exc}"


NO_REGISTRY_ROW = "no-registry-row"
DISPOSITIONED_RESAVE = "dispositioned-resave"


def _accepted_shas(dispositions, card_id: str, registry_sha: str) -> frozenset[str]:
    """New shas a ``resave-content-verified`` row allows over ``registry_sha`` for the card."""
    from pursue_index.byte_dispositions import RESAVE_CONTENT_VERIFIED

    return frozenset(
        d.new_sha256
        for (cid, _), d in (dispositions or {}).items()
        if cid == card_id
        and d.disposition == RESAVE_CONTENT_VERIFIED
        and d.old_sha256 == registry_sha
    )


def _is_unchecked_first_download(card: CardMetadata, kwargs: dict[str, str]) -> bool:
    """A PDF about to be fetched for the first time with no sha to verify against."""
    if card.asset_type != "PDF" or kwargs:
        return False
    target = asset_path_for(card)
    return target is not None and not (target.exists() and target.stat().st_size > 0)


def _request_headers() -> dict[str, str]:
    return {
        "User-Agent": settings.scrape_user_agent
        or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.war.gov/UFO/",
    }


async def _fetch_card(
    client: httpx.AsyncClient,
    card: CardMetadata,
    refresh_shas: dict[str, str],
    registry_shas: dict[str, str],
    outcomes: dict[str, str],
    dispositions,
    failed: dict[str, str],
) -> Path | None:
    """One card's download: pick its sha check, fetch, record its outcome or failure."""
    kwargs: dict[str, str] = {}
    if card.card_id in refresh_shas:
        kwargs["expected_sha"] = refresh_shas[card.card_id]
    elif card.asset_type == "PDF" and card.card_id in registry_shas:
        kwargs["registry_sha"] = registry_shas[card.card_id]
    unchecked = _is_unchecked_first_download(card, kwargs)
    accept = (
        _accepted_shas(dispositions, card.card_id, kwargs["registry_sha"])
        if "registry_sha" in kwargs
        else frozenset()
    )
    try:
        if accept:  # a disposition can only matter when one covers this card
            kwargs.update(accept_shas=accept, outcomes=outcomes)
        path = await _download_one(client, card, **kwargs)
        if unchecked and path is not None:
            outcomes[card.card_id] = NO_REGISTRY_ROW
            log.warning("download.no_registry_row", card_id=card.card_id)
        return path
    except Exception as exc:  # noqa: BLE001 - one bad card must not abort the gather
        # Record the card and carry on with the rest.
        reason = _failure_reason(exc)
        log.error("download.failed", card_id=card.card_id, error=reason)
        failed[card.card_id] = reason
        return None


async def download_all(
    manifest: Manifest,
    refresh_shas: dict[str, str] | None = None,
    registry_shas: dict[str, str] | None = None,
    outcomes: dict[str, str] | None = None,
    dispositions=None,
) -> list[Path | None]:
    """Download every asset in the manifest with bounded concurrency.

    ``refresh_shas`` maps ``bytes-changed`` card_ids to the registry's latest sha;
    those cards are re-fetched and verified even when a local file exists.
    ``registry_shas`` maps card_ids to the registry's latest PDF sha; a PDF card
    downloaded for the first time must hash to it. A PDF with no registry row yet
    (ingest runs before the daily archive registers it) is downloaded unchecked,
    warned about, and recorded in ``outcomes`` as ``no-registry-row``; only a row
    that exists and disagrees with the fetched bytes fails the card, unless
    ``dispositions`` holds a ``resave-content-verified`` row whose ``old_sha256`` is
    that registry sha and whose ``new_sha256`` is the fetched sha (outcome
    ``dispositioned-resave``).
    """
    refresh_shas = refresh_shas or {}
    outcomes = outcomes if outcomes is not None else {}
    registry_shas = registry_shas or {}
    sem = asyncio.Semaphore(settings.download_concurrency)
    failed: dict[str, str] = {}
    headers = _request_headers()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, read=300.0),
        headers=headers,
        follow_redirects=True,
    ) as client:

        async def _bounded(card: CardMetadata) -> Path | None:
            async with sem:
                return await _fetch_card(
                    client, card, refresh_shas, registry_shas, outcomes, dispositions, failed
                )

        results = await asyncio.gather(
            *(_bounded(c) for c in manifest.cards), return_exceptions=False
        )

    downloaded = sum(1 for r in results if r is not None)
    log.info(
        "download.summary",
        downloaded=downloaded,
        total=len(manifest.cards),
        failed=len(failed),
        no_registry_row=sum(1 for v in outcomes.values() if v == NO_REGISTRY_ROW),
    )
    if failed:
        raise DownloadBatchError(failed)
    return results
