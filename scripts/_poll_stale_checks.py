"""Byte-level staleness checks for the tranche poll (#157, #176).

Both compare freshly fetched CSV bytes against prior state already on
disk -- the byte archive or the current manifest -- rather than against
the guard's own seen/Last-Modified history (``_poll_guard.py``). Split
into their own module to keep ``_poll_guard.py`` under the function-count
threshold, the same reason ``_poll_results.py``/``_poll_gh_io.py`` were
split out of ``poll_pursue.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

from pursue_index.scrape.csv_fetcher import parse_csv
from pursue_index.scrape.encoding_equivalence import is_encoding_only_change
from pursue_index.scrape.manifest import load_manifest

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def encoding_only_vs_archive(archive_dir: Path | None, old_sha: str, body: bytes) -> bool:
    """Is ``body`` an encoding-only change from the archived ``old_sha``?

    Fails closed: without the prior bytes, or when ``old_sha`` (read from
    repo files) isn't a 64-hex sha fit to name an archive path, the change
    counts as real.
    """
    if archive_dir is None or not _SHA256_HEX.fullmatch(old_sha):
        return False
    prior = archive_dir / f"{old_sha}.csv"
    if not prior.exists():
        return False
    return is_encoding_only_change(prior.read_bytes(), bytes(body))


def is_row_subset_of_manifest(manifest_path: Path | None, body: bytes) -> bool:
    """Is ``body``'s card-id set a non-empty, strict subset of the
    manifest at ``manifest_path``'s?

    A strict subset is evidence of an older or truncated copy (upstream
    tranches only grow the card set) -- a signal independent of
    ``Last-Modified``. Fails closed: a missing manifest, or a CSV/manifest
    that doesn't parse, never counts as a subset, so a parse failure can't
    silently suppress a real new tranche.
    """
    if manifest_path is None or not manifest_path.exists():
        return False
    try:
        candidate_ids = {card.card_id for card in parse_csv(body)}
        current_ids = {card.card_id for card in load_manifest(manifest_path).cards}
    except Exception:  # noqa: BLE001 — any parse failure fails closed
        return False
    return bool(candidate_ids) and candidate_ids < current_ids
