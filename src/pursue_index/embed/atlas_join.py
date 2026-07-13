"""Join the alex-zhang42 VLM corpus to our scrape manifest by card_id.

.. deprecated:: 2026-07-11
    RETIRED. The alex-zhang42 augment corpus is no longer part of the operated
    retrieval pipeline (replaced by our own Opus-4.8 image-observations vision
    pass; ``--augment-from`` stripped from ``pursue embed run``). This joiner is
    retained for historical reproducibility only — do NOT re-enable it in the
    embed path.


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

Integrity: the corpus is a committed, sha256-pinned artifact. Every load
verifies the bytes against the adjacent ``.sha256`` sidecar before
parsing — a missing or mismatched sidecar fails the run, with an
explicit env-flag opt-out (``PURSUE_AUGMENT_SKIP_HASH_CHECK=1``) for
operators regenerating the corpus locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote

from pursue_index.scrape.normalize import stable_card_id
from pursue_index.scrape.types import Manifest

# Operational ceiling on the join miss-rate threshold. A threshold above
# 50% disables the safety net entirely (every miss is "fine"); the
# operational case for >50% does not exist on a hash-pinned corpus, so
# we reject those values at the call boundary as fail-closed posture.
MAX_MISS_RATE_THRESHOLD = 0.5

# Env flag that explicitly opts out of sha256 verification. Intended for
# operators regenerating the corpus mid-edit; CI and production paths
# should leave this unset.
_SKIP_HASH_CHECK_ENV = "PURSUE_AUGMENT_SKIP_HASH_CHECK"

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


def _validate_threshold(threshold: float) -> None:
    """Reject thresholds outside ``[0.0, MAX_MISS_RATE_THRESHOLD]``.

    A threshold of 1.0 silently disables the join quality gate — the
    fail-open posture flagged in laverna SEC-002. We clamp at the call
    boundary so every code path (CLI flag, programmatic caller) gets the
    same protection.
    """
    if threshold < 0.0 or threshold > MAX_MISS_RATE_THRESHOLD:
        raise ValueError(
            f"miss_rate_threshold must be in [0.0, "
            f"{MAX_MISS_RATE_THRESHOLD}]; got {threshold}"
        )


def _read_sha256_sidecar(corpus_jsonl: Path) -> str | None:
    """Locate ``.sha256`` next to ``corpus_jsonl`` and return the hash.

    Accepts both the ``<stem>.sha256`` (suffix-replaced) and
    ``<filename>.sha256`` (suffix-appended) forms — both are in the wild
    depending on which build script wrote them. Returns ``None`` if
    neither variant exists.
    """
    candidates = [
        corpus_jsonl.with_suffix(".sha256"),
        corpus_jsonl.parent / (corpus_jsonl.name + ".sha256"),
    ]
    for path in candidates:
        if path.exists():
            text = path.read_text().strip()
            return text.split()[0] if text else ""
    return None


def _hash_corpus_file(corpus_jsonl: Path) -> str:
    h = hashlib.sha256()
    with corpus_jsonl.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(corpus_jsonl: Path) -> None:
    """Hash the corpus and compare against its ``.sha256`` sidecar.

    The sidecar is a hard requirement on the pinned-revision corpus; a
    missing or mismatched sidecar means the bytes have drifted from what
    the embed run committed against, so we refuse to continue. Operators
    regenerating the corpus mid-edit can opt out via
    ``PURSUE_AUGMENT_SKIP_HASH_CHECK=1``.
    """
    if os.environ.get(_SKIP_HASH_CHECK_ENV) == "1":
        return
    expected = _read_sha256_sidecar(corpus_jsonl)
    if expected is None:
        raise AtlasJoinError(
            f"atlas corpus integrity check: no sha256 sidecar next to "
            f"{corpus_jsonl}. Expected ``{corpus_jsonl.with_suffix('.sha256')}`` "
            f"or ``{corpus_jsonl}.sha256``. Set "
            f"{_SKIP_HASH_CHECK_ENV}=1 to bypass during local regeneration."
        )
    actual = _hash_corpus_file(corpus_jsonl)
    if actual != expected:
        raise AtlasJoinError(
            f"atlas corpus sha256 mismatch: file hashes to {actual} "
            f"but sidecar declares {expected}. Refusing to load — "
            f"the bytes have drifted from the committed revision."
        )


def _extract_source_url(rec: dict) -> str:
    """Pull and validate ``source_url`` from a single corpus record.

    Empty or missing ``source_url`` is a malformed record (not a
    legitimate miss): hashing the empty string is deterministic but
    will never match a real card, so the record would silently inflate
    the miss rate. Surface it as an error instead.
    """
    if "source_url" not in rec:
        raise AtlasJoinError(
            "atlas corpus record is missing source_url field"
        )
    url = rec["source_url"]
    if not isinstance(url, str) or not url.strip():
        raise AtlasJoinError(
            f"atlas corpus record has empty source_url; record={rec!r}"
        )
    return url


def _parse_corpus_records(
    corpus_jsonl: Path,
    known_ids: set[str],
    canonical_lookup: dict[str, str],
) -> tuple[dict[tuple[str, int], list[str]], list[str], int]:
    """Read the corpus and partition into ``(matches, misses, total)``.

    Corrupt JSONL rows are logged and skipped rather than aborting the
    entire ingest. The augment corpus comes from an external source
    (alex-zhang42/ufo-pursue-open-atlas) — we observed 4 corrupt rows in
    a 4156-row file on 2026-05-11, all clustered on consecutive line
    numbers (448-451), which fit the profile of a single bad input
    during the upstream generation that cascaded into a handful of
    adjacent rows. Failing the entire embed run for a sub-1% corruption
    rate would mean losing the augmented-retrieval differentiator over
    a few image-description entries that we can't fix from our side
    anyway. Track via the returned ``parse_errors`` count so an
    operator-visible threshold check can still catch a wholesale
    corpus break.
    """
    out: dict[tuple[str, int], list[str]] = {}
    misses: list[str] = []
    total = 0
    parse_errors = 0
    with corpus_jsonl.open(encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                parse_errors += 1
                if parse_errors <= 5:
                    # Keep the log readable on a wholesale break — first
                    # five samples is enough to diagnose.
                    print(
                        f"atlas_join: skip corrupt row at line {line_num} "
                        f"(col {exc.colno}): {exc.msg}",
                        flush=True,
                    )
                continue
            source_url = _extract_source_url(rec)
            card_id = _resolve_card_id(
                source_url, known_ids, canonical_lookup
            )
            if card_id is None:
                misses.append(source_url)
                continue
            tags = _dedupe_tags(rec.get("image_tags") or [])
            if not tags:
                continue
            out[(card_id, int(rec["page_num"]))] = tags
    if parse_errors > 0:
        # If more than 5% of rows are corrupt, the upstream corpus has a
        # systemic problem we shouldn't quietly absorb. Raise so the
        # operator can investigate instead of shipping a half-augmented
        # index.
        corrupt_rate = parse_errors / max(total, 1)
        print(
            f"atlas_join: {parse_errors}/{total} rows corrupt "
            f"({corrupt_rate:.2%})",
            flush=True,
        )
        if corrupt_rate > 0.05:
            raise AtlasJoinError(
                f"atlas corpus has {parse_errors}/{total} corrupt rows "
                f"({corrupt_rate:.2%}) — refusing to embed; regenerate "
                f"the corpus or set PURSUE_AUGMENT_SKIP_HASH_CHECK=1 "
                f"if this is expected"
            )
    return out, misses, total


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
            Must lie in ``[0.0, MAX_MISS_RATE_THRESHOLD]`` (50%) — a
            higher value would silently disable the safety net.

    Returns:
        A dict keyed by ``(our_card_id, page_num)`` with a deduped list of
        ``image_tag`` strings per page. Pages with no usable tags are
        omitted entirely.

    Raises:
        ValueError: if ``miss_rate_threshold`` is outside the allowed range.
        AtlasJoinError: if the corpus file's sha256 doesn't match its
            ``.sha256`` sidecar, if a record has a missing/empty
            ``source_url``, or if the miss rate exceeds
            ``miss_rate_threshold``. Records with an empty ``image_tags``
            list do NOT count as misses — they're a legitimate
            "page has no images" signal.
    """
    _validate_threshold(miss_rate_threshold)
    _verify_sha256(corpus_jsonl)
    known_ids = {c.card_id for c in manifest.cards}
    canonical_lookup = _build_canonical_lookup(manifest)
    out, misses, total = _parse_corpus_records(
        corpus_jsonl, known_ids, canonical_lookup
    )
    _enforce_miss_rate(misses, total, miss_rate_threshold)
    return out
