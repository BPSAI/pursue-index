"""Offline snapshot + diff generator from raw CSV bytes (Sprint 6, T6.1).

The credential-free poll lane fetches the upstream CSV bytes elsewhere
(no R2, no CLI) and hands them here. ``generate_snapshot_diff`` is a
network-free, credential-free entry point that:

  * parses the bytes with the existing ``parse_csv`` -> ``build_manifest``;
  * rotates the prior ``latest.json`` into the public snapshot mirror via
    ``rotate_to_snapshot`` (preserving the old side of the diff);
  * writes the new manifest as ``snapshots/<new_sha>.json`` so the
    DiffIsland has the new side immediately, without waiting for the next
    poll to rotate it out;
  * computes the ``ManifestDiff`` (added/removed) against the prior
    ``latest.json``, the per-card ``field_changes`` (reusing the
    tranche-diff ``field_diff`` comparison), and any brand-new CSV column
    header not present in the prior snapshot.

It deliberately does NOT call ``fetch_raw_csv`` and never touches R2 or
any credential — bytes in, snapshot files + a structured diff out. The
``scripts/poll_snapshot.py`` shell wraps this for the GH Actions runner
using the same ``src/``-injection pattern as ``pdf_health``.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.scrape.csv_fetcher import _MAPPED_KEYS, build_manifest, parse_csv
from pursue_index.scrape.manifest import load_manifest
from pursue_index.scrape.snapshots import (
    DEFAULT_CANONICAL_DIR,
    DEFAULT_PUBLIC_DIR,
    _rebuild_index,
    rotate_to_snapshot,
)
from pursue_index.scrape.types import CardMetadata, Manifest, ManifestDiff
from pursue_index.tranche import field_diff


@dataclass(frozen=True)
class SnapshotDiffResult:
    """Structured result of an offline snapshot+diff run."""

    added: list[CardMetadata]
    removed: list[CardMetadata]
    field_changes: list[dict[str, Any]]
    new_columns: list[str]


def generate_snapshot_diff(
    raw_csv: bytes,
    *,
    source_url: str,
    latest_path: Path,
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    public_dir: Path = DEFAULT_PUBLIC_DIR,
) -> SnapshotDiffResult:
    """Build a manifest from ``raw_csv`` and diff it against the prior
    ``latest_path`` manifest, writing both sides into the snapshot mirror.

    No network calls (does not invoke ``fetch_raw_csv``) and no R2 /
    credential access — the caller supplies the already-fetched bytes.
    """
    new_manifest = build_manifest(raw_csv, parse_csv(raw_csv), source_url)

    prior = load_manifest(latest_path) if latest_path.exists() else None

    # Rotate the prior latest.json into snapshots/<prior_sha>.json (public +
    # canonical) BEFORE we add the new side, so both ends of the diff land
    # in the mirror.
    rotate_to_snapshot(latest_path, canonical_dir=canonical_dir, public_dir=public_dir)
    _write_new_snapshot(new_manifest, canonical_dir, public_dir)

    if prior is None:
        return SnapshotDiffResult(
            added=list(new_manifest.cards),
            removed=[],
            field_changes=[],
            new_columns=_new_columns(raw_csv, prior_cards=[]),
        )

    diff: ManifestDiff = new_manifest.diff(prior)
    return SnapshotDiffResult(
        added=diff.added,
        removed=diff.removed,
        field_changes=_field_changes(prior, new_manifest),
        new_columns=_new_columns(raw_csv, prior_cards=prior.cards),
    )


def _write_new_snapshot(
    manifest: Manifest, canonical_dir: Path, public_dir: Path
) -> None:
    """Write the new manifest as ``snapshots/<csv_sha>.json`` to both the
    canonical and public mirrors, then refresh both indexes so DiffIsland
    can label the new entry. Serialization matches ``save_manifest`` so the
    bytes are identical to what a normal scrape-run rotation would produce.
    """
    canonical_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump_json(indent=2, by_alias=True).encode("utf-8")
    name = f"{manifest.csv_sha256}.json"
    (canonical_dir / name).write_bytes(payload)
    (public_dir / name).write_bytes(payload)
    _rebuild_index(canonical_dir, public_dir)


def _field_changes(prior: Manifest, new: Manifest) -> list[dict[str, Any]]:
    """Per-card field diffs for card_ids present in both manifests, reusing
    the tranche-diff ``field_diff`` comparison. JSON-mode dumps so URLs and
    datetimes compare as the strings they serialize to in the snapshot.
    """
    prior_by_id = {c.card_id: c.model_dump(mode="json", by_alias=True) for c in prior.cards}
    new_by_id = {c.card_id: c.model_dump(mode="json", by_alias=True) for c in new.cards}
    out: list[dict[str, Any]] = []
    for cid in sorted(set(prior_by_id) & set(new_by_id)):
        diffs = field_diff(prior_by_id[cid], new_by_id[cid])
        if diffs:
            out.append({"card_id": cid, "diffs": diffs})
    return out


def _new_columns(raw_csv: bytes, *, prior_cards: list[CardMetadata]) -> list[str]:
    """CSV headers in the new bytes that the prior snapshot never saw.

    "Known" = the columns the parser maps to model fields (``_MAPPED_KEYS``)
    plus any unmapped columns carried in prior cards' ``raw`` dicts. A
    header outside that set is a genuine schema addition.
    """
    known = set(_MAPPED_KEYS)
    for card in prior_cards:
        known |= set(card.raw)
    return sorted(h for h in _csv_headers(raw_csv) if h not in known)


def _csv_headers(raw_csv: bytes) -> set[str]:
    """Header set from the raw CSV, cleaned the same way ``parse_csv``
    cleans column keys (stripped, dropping blank / padding columns)."""
    text = raw_csv.decode("utf-8-sig")  # CSV is UTF-8 with BOM
    header = next(csv.reader(io.StringIO(text)), [])
    return {h.strip() for h in header if h and not h.startswith(" ")}
