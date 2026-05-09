"""Join the alex-zhang42 VLM corpus to our scrape manifest by card_id.

The dataset (`alex-zhang42/ufo-pursue-open-atlas`) ships per-page records
with a ``source_url`` field that mirrors war.gov's PDF URL. Our scrape
stage hashes ``asset_url`` (or ``title`` as fallback) into a 16-hex
``card_id`` via ``pursue_index.scrape.normalize.stable_card_id``. When
both pipelines saw the same war.gov URL byte-for-byte the join is a one-
shot hash equality; in practice their pipeline normalizes filenames
(spaces -> underscores, lowercased) where ours preserves the literal
percent-encoded form, so the loader also retries via a canonical-URL
table built from our manifest.

Schema reference (verified against the parquet at revision
b0f0c79924b88d339846aa9fc4283958fe15682b):

- ``source_url``: str, war.gov PDF URL
- ``page_num``: int, 1-indexed
- ``image_tags``: list[str], each string is the inside of a ``*Image: ...*``
  tag in the page's Markdown text
- ``sha256``: str, source-PDF hash (available as a tiebreaker; not used by
  the URL-join path here, but kept in the record so a future caller can
  cross-check against our OCR ``meta.json``'s ``pdf_sha256`` field)

The join is keyed by **our** card_id so the embed pipeline can look up
augmentation by the same key it already uses internally.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

from pursue_index.scrape.normalize import stable_card_id
from pursue_index.scrape.types import Manifest

# Squash any run of underscores or whitespace into a single underscore.
# The two pipelines disagree on which to use as a separator (war.gov
# preserves spaces in the served filename; alex-zhang42 lowercases and
# replaces spaces with underscores), so canonicalization erases that
# disagreement.
_WS_OR_UNDERSCORE_RUN = re.compile(r"[\s_]+")


class AtlasJoinError(RuntimeError):
    """Raised when the atlas->manifest join fails its match-rate threshold.

    Carries a sample of the first few un-matched ``source_url`` values so
    the operator can diagnose without re-running the loader.
    """


def canonicalize_url(url: str) -> str:
    """Lowercase, percent-decode, and collapse whitespace/underscore runs.

    Used to match URLs across pipelines that disagree on filename
    encoding (literal space vs ``%20`` vs underscore). NOT used to compute
    card_ids — those remain hash-of-raw-URL — only as a fallback lookup
    when the direct hash misses.
    """
    decoded = unquote(url).lower().strip()
    return _WS_OR_UNDERSCORE_RUN.sub("_", decoded)


def _build_canonical_lookup(manifest: Manifest) -> dict[str, str]:
    """Map ``canonicalize_url(asset_url) -> card_id`` for every card."""
    out: dict[str, str] = {}
    for card in manifest.cards:
        if card.asset_url is None:
            continue
        out[canonicalize_url(str(card.asset_url))] = card.card_id
    return out


def _resolve_card_id(
    source_url: str, known_ids: set[str], canonical_lookup: dict[str, str]
) -> str | None:
    """Hash-first, canonical-fallback. Returns our card_id or None."""
    direct = stable_card_id(source_url, "")
    if direct in known_ids:
        return direct
    return canonical_lookup.get(canonicalize_url(source_url))


def _dedupe_tags(tags: list[str]) -> list[str]:
    """Preserve first-seen order, drop blanks, drop exact duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        cleaned = tag.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _enforce_miss_rate(
    misses: list[str], total: int, threshold: float
) -> None:
    """Raise AtlasJoinError if the miss rate exceeds the threshold."""
    if total == 0:
        return
    rate = len(misses) / total
    if rate > threshold:
        sample = "\n  ".join(misses[:10])
        raise AtlasJoinError(
            f"atlas join miss rate {rate:.1%} exceeds threshold "
            f"{threshold:.1%} ({len(misses)}/{total} unmatched). "
            f"First un-matched source_urls:\n  {sample}"
        )


def load_atlas_index(
    corpus_jsonl: Path,
    manifest: Manifest,
    *,
    miss_rate_threshold: float = 0.01,
) -> dict[tuple[str, int], list[str]]:
    """Read the atlas corpus.jsonl and return ``{(card_id, page): [tag,...]}``.

    Args:
        corpus_jsonl: Path to ``alex-zhang42-corpus.jsonl``.
        manifest: Our scrape manifest (used to look up card_ids).
        miss_rate_threshold: Fraction of records allowed to be unmatched
            before the loader raises ``AtlasJoinError``. Default 1%.

    Returns:
        A dict keyed by ``(our_card_id, page_num)`` with a deduped list of
        ``image_tag`` strings per page. Pages with no usable tags are
        omitted entirely.

    Raises:
        AtlasJoinError: if the miss rate exceeds ``miss_rate_threshold``.
            Records with an empty ``image_tags`` list do NOT count as
            misses — they're a legitimate "page has no images" signal.
    """
    known_ids = {c.card_id for c in manifest.cards}
    canonical_lookup = _build_canonical_lookup(manifest)
    out: dict[tuple[str, int], list[str]] = {}
    misses: list[str] = []
    total = 0

    with corpus_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            rec = json.loads(line)
            card_id = _resolve_card_id(
                rec["source_url"], known_ids, canonical_lookup
            )
            if card_id is None:
                misses.append(rec["source_url"])
                continue
            tags = _dedupe_tags(rec.get("image_tags") or [])
            if not tags:
                continue
            out[(card_id, int(rec["page_num"]))] = tags

    _enforce_miss_rate(misses, total, miss_rate_threshold)
    return out
