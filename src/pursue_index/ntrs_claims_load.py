"""Reading the stored NTRS claims, for the stages that resolve against them.

The coverage report reads ``data/provenance/ntrs-claims.json`` the same way it
reads the source catalogue: a missing file is not an error (a checkout that has
never run the NTRS search simply has no NTRS claims), and every stored claim is
rebuilt through :class:`~pursue_index.resolved_claim.ResolvedClaim`, so one the
constructor refuses is refused here too.

A file written before claims named a row (no entry carries a ``row_key``) is
migrated here and nowhere else: each of its claims is applied to every row of its
file (``file_key()``: the ``card_id``), and says so with
``row_key_migrated_from: "card_id"``. A claim whose file has no row in the manifest
stays unkeyed, so it matches nothing and is counted. In a file that does carry
``row_key``, an empty one matches no row.

The migration fails closed. Rows sharing a ``card_id`` that name different assets
(``asset_url``, else ``asset_filename``) are more than one file, and an old claim
may carry the asset it was found for. A claim is applied only when exactly one
asset is determined (the file's single asset, or the one the claim names and some
row has); otherwise nothing is applied and the claim is counted in
``ntrs_claims_migration_ambiguous_count``. It is never guessed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pursue_index.card_id import CARD_ID_PATTERN
from pursue_index.file_counts import file_key_of
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.row_key import row_keys

__all__ = [
    "NTRS_CLAIMS_PATH",
    "NtrsClaims",
    "NtrsOutcome",
    "load_ntrs_claims",
    "read_ntrs_claims",
    "resolve_ntrs_claims",
]

NTRS_CLAIMS_PATH = Path("data") / "provenance" / "ntrs-claims.json"


@dataclass(frozen=True)
class NtrsClaims:
    """Stored claims together with the manifest markers they were built from."""

    claims: list[ResolvedClaim]
    csv_sha256: str | None
    corpus_manifest_url: str | None
    refused_claims: int = 0
    migration_ambiguous: int = 0


_ASSET_FIELDS = ("asset_url", "asset_filename")


def _asset(record: dict[str, Any]) -> str:
    """The asset a manifest row or an old claim names: ``asset_url``, else ``asset_filename``."""
    return next((str(record[f]).strip() for f in _ASSET_FIELDS if str(record.get(f) or "").strip()), "")


def _migrated(
    claim: ResolvedClaim, raw: dict[str, Any], cards: Sequence[dict[str, Any]]
) -> list[ResolvedClaim] | None:
    """One labelled copy of an unkeyed claim per row of its file; ``None`` when the file is ambiguous.

    A file with no row in the manifest returns the claim itself, unkeyed.
    """
    rows = [
        (card, key)
        for card, key in zip(cards, row_keys(cards), strict=True)
        if file_key_of(str(card.get("card_id") or ""), key) == claim.card_id
    ]
    if not rows:
        return [claim]
    named = _asset(raw)
    assets = {a for card, _ in rows if (a := _asset(card))}
    if named:
        rows = [(card, key) for card, key in rows if _asset(card) == named]
        if not rows:
            return None
    elif len(assets) > 1:
        return None
    return [replace(claim, row_key=key, row_key_migrated_from="card_id") for _, key in rows]


def load_ntrs_claims(data: dict[str, Any], cards: Sequence[dict[str, Any]] | None = None) -> NtrsClaims:
    """The positive claims held by a parsed ``ntrs-claims.json``, with their markers.

    ``cards`` are the manifest rows a pre-keying file's claims are migrated onto;
    without them such claims stay unkeyed.
    """
    # Files written before the key was renamed carry ``source_manifest``.
    url = data.get("corpus_manifest_url", data.get("source_manifest"))
    rows = data.get("claims", [])
    kept = [row for row in rows if _valid_card_id(row.get("card_id"))]
    claims = [ResolvedClaim.from_dict(row) for row in kept]
    ambiguous = 0
    if cards is not None and rows and not any("row_key" in row for row in rows):
        migrated: list[ResolvedClaim] = []
        for claim, raw in zip(claims, kept, strict=True):
            moved = _migrated(claim, raw, cards)
            ambiguous += moved is None
            migrated.extend(moved or [])
        claims = migrated
    return NtrsClaims(
        claims=claims,
        csv_sha256=data.get("csv_sha256"),
        corpus_manifest_url=url,
        refused_claims=len(rows) - len(kept),
        migration_ambiguous=ambiguous,
    )


def _valid_card_id(card_id: object) -> bool:
    """A claim is indexed by card_id, so one without a valid id is never loaded."""
    return isinstance(card_id, str) and CARD_ID_PATTERN.fullmatch(card_id) is not None


def read_ntrs_claims(repo_root: Path, cards: Sequence[dict[str, Any]] | None = None) -> NtrsClaims | None:
    """Load the tracked NTRS claims under ``repo_root``, or ``None`` if absent."""
    path = repo_root / NTRS_CLAIMS_PATH
    if not path.exists():
        return None
    return load_ntrs_claims(json.loads(path.read_text()), cards)


@dataclass(frozen=True)
class NtrsOutcome:
    """What a run does with the stored claims: the claims to apply, and a notice if it left them out."""

    claims: list[ResolvedClaim]
    applied: bool
    csv_sha256: str | None
    notice: str | None
    migration_ambiguous: int = 0

    def summary_fields(self) -> dict[str, Any]:
        return {
            "ntrs_claims_applied": self.applied,
            "ntrs_claims_csv_sha256": self.csv_sha256,
            "ntrs_claims_migration_ambiguous_count": self.migration_ambiguous,
        }


def resolve_ntrs_claims(repo_root: Path, manifest: dict[str, Any]) -> NtrsOutcome:
    """The claims to apply for ``manifest``; stale ones are left out whole, with a notice.

    A missing file means no claims and no notice. A file whose ``csv_sha256`` is
    missing, empty or different from the manifest's applies nothing, never a part.
    """
    stored = read_ntrs_claims(repo_root, manifest.get("cards", []))
    if stored is None:
        return NtrsOutcome([], False, None, None)
    sha = stored.csv_sha256 or None
    if sha is None or sha != manifest.get("csv_sha256"):
        return NtrsOutcome([], False, sha, f"NTRS claims not applied: claims file is for csv {sha or '<none>'}", stored.migration_ambiguous)
    return NtrsOutcome(stored.claims, True, sha, None, stored.migration_ambiguous)
