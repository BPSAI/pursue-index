"""Demote a Class C quarantine to a rename on byte evidence (R7C.12).

``scripts/tranche_diff.py --bytes-dir DIR`` hands every Class C candidate
(new card, new bytes, title continuity with a removed card) to
``tranche_bytes.classify_bytes``. When the new bytes are the matched old
card's bytes plus a metadata-only incremental update, the row moves from
``quarantined`` to ``renames_metadata_only`` (``RESAVE_BUCKET``) and
``pursue ingest approve`` aliases it with ``method: "metadata-only-resave"``
(``RESAVE_METHOD``) without an ``--approve-rename`` flag.

Bytes-dir naming convention -- content-addressed, like the R2 archive's
``archive/<sha256>.<ext>`` keys (``scripts/r2_archive_assets.py``)::

    <bytes-dir>/<byte_sha256>.pdf

  * the OLD file's sha is the matched old card's latest
    ``data/asset-bytes-registry.jsonl`` row (last row wins, as everywhere
    else that reads the registry);
  * the NEW file's sha is the one tranche_diff just fetched for the new
    card (the row's ``new_byte_sha256``).

So a bytes-dir is just a local copy of the relevant archive objects, and
each file is re-hashed before use: a file whose bytes do not hash to its
name is treated as absent. Absent evidence (no ``--bytes-dir``, a missing
or misnamed file, no new sha, no registry row, a ``content-changed``
verdict) leaves the row quarantined and the diff byte-identical to a run
without ``--bytes-dir``: the new bucket and its summary count appear only
when at least one row moved.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pursue_index.classifier_id import classifier_id
from pursue_index.pdf_crosscheck import CROSSCHECKS
from pursue_index.tranche_bytes import METADATA_ONLY, classify_bytes

__all__ = [
    "RESAVE_BUCKET",
    "RESAVE_METHOD",
    "ResaveCheck",
    "bytes_dir_check",
    "demote_resaves",
    "resave_counts",
]

_SHA256 = re.compile(r"[0-9a-f]{64}")
RESAVE_BUCKET = "renames_metadata_only"
RESAVE_METHOD = "metadata-only-resave"

# (old_card_id, new_byte_sha256) -> the old byte sha when the new bytes are
# a metadata-only re-save of that card's bytes, else None.
ResaveCheck = Callable[[str, str | None], str | None]


def _verified_path(bytes_dir: Path, sha: str | None) -> Path | None:
    if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
        return None
    path = bytes_dir / f"{sha}.pdf"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    return path if hashlib.sha256(data).hexdigest() == sha else None


def bytes_dir_check(
    bytes_dir: Path | None, registry: dict[str, list[dict[str, Any]]],
) -> ResaveCheck | None:
    """The ``resave_check`` for ``diff_tranches``; ``None`` without a dir."""
    if bytes_dir is None:
        return None

    def check(old_card_id: str, new_sha: str | None) -> str | None:
        rows = registry.get(old_card_id) or []
        old_sha = rows[-1].get("byte_sha256") if rows else None
        old_path = _verified_path(bytes_dir, old_sha)
        new_path = _verified_path(bytes_dir, new_sha)
        if old_path is None or new_path is None:
            return None
        try:
            verdict = classify_bytes(old_path, new_path)
        except FileNotFoundError:
            return None
        return old_sha if verdict == METADATA_ONLY else None

    return check


def _resave_row(
    row: dict[str, Any], old_card_id: str, old_sha: str, match: dict[str, Any],
) -> dict[str, Any]:
    return {
        "old_card_id": old_card_id,
        "new_card_id": row["new_card_id"],
        "byte_sha256": row["new_byte_sha256"],
        "old_byte_sha256": old_sha,
        "verdict": METADATA_ONLY,
        "classifier": classifier_id(),
        "crosscheck": list(CROSSCHECKS),
        "method": RESAVE_METHOD,
        "new_title": row.get("new_title"),
        "new_asset_filename": row.get("new_asset_filename"),
        "new_asset_url": row.get("new_asset_url"),
        "continuity_reasons": match["reasons"],
    }


def _first_resave(row: dict[str, Any], check: ResaveCheck, taken: set[str]) -> dict | None:
    """Strongest-ranked matched old card the new bytes re-save, if any."""
    matches = {m["card_id"]: m for m in row.get("matches", [])}
    for old_card_id in row.get("matched_against", []):
        # An id with no ``matches`` entry cannot be audited; leave it quarantined.
        if old_card_id in taken or old_card_id not in matches:
            continue
        old_sha = check(old_card_id, row.get("new_byte_sha256"))
        if old_sha is not None:
            return _resave_row(row, old_card_id, old_sha, matches[old_card_id])
    return None


def demote_resaves(
    buckets: dict[str, Any], check: ResaveCheck | None, matched_old_ids: set[str],
) -> set[str]:
    """Move metadata-only re-saves out of ``buckets["quarantined"]``.

    Adds ``buckets[RESAVE_BUCKET]`` only when a row moved; returns the old
    card_ids those rows alias (so they leave the ``removed`` list, as Class A
    old ids do). An old card already claimed by a rename is never re-used.
    """
    if check is None:
        return set()
    kept, moved, taken = [], [], set(matched_old_ids)
    for row in buckets["quarantined"]:
        resave = _first_resave(row, check, taken)
        if resave is None:
            kept.append(row)
        else:
            moved.append(resave)
            taken.add(resave["old_card_id"])
    if moved:
        buckets["quarantined"] = kept
        buckets[RESAVE_BUCKET] = moved
    return {r["old_card_id"] for r in moved}


def resave_counts(buckets: dict[str, Any]) -> dict[str, int]:
    """The summary entry for the bucket -- empty when the bucket is absent."""
    return {RESAVE_BUCKET: len(buckets[RESAVE_BUCKET])} if RESAVE_BUCKET in buckets else {}
