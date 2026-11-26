"""Reading the stored NTRS claims, for the stages that resolve against them.

The coverage report reads ``data/provenance/ntrs-claims.json`` the same way it
reads the source catalogue: a missing file is not an error (a checkout that has
never run the NTRS search simply has no NTRS claims), and every stored claim is
rebuilt through :class:`~pursue_index.resolved_claim.ResolvedClaim`, so one the
constructor refuses is refused here too.

A file written before claims named a row (no entry carries a ``row_key``) is
migrated here and nowhere else: each of its claims is applied to every row of its
``card_id``'s file, and says so with ``row_key_migrated_from: "card_id"``. A claim
whose file has no row in the manifest stays unkeyed, so it matches nothing and is
counted. In a file that does carry ``row_key``, an empty one matches no row.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pursue_index.card_id import CARD_ID_PATTERN
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


def _migrated(claim: ResolvedClaim, cards: Sequence[dict[str, Any]]) -> list[ResolvedClaim]:
    """One labelled copy of an unkeyed claim per row of its file; itself if the file has none."""
    keys = [k for card, k in zip(cards, row_keys(cards), strict=True) if card.get("card_id") == claim.card_id]
    return [replace(claim, row_key=k, row_key_migrated_from="card_id") for k in keys] or [claim]


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
    if cards is not None and rows and not any("row_key" in row for row in rows):
        claims = [moved for claim in claims for moved in _migrated(claim, cards)]
    return NtrsClaims(
        claims=claims,
        csv_sha256=data.get("csv_sha256"),
        corpus_manifest_url=url,
        refused_claims=len(rows) - len(kept),
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

    def summary_fields(self) -> dict[str, Any]:
        return {"ntrs_claims_applied": self.applied, "ntrs_claims_csv_sha256": self.csv_sha256}


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
        return NtrsOutcome([], False, sha, f"NTRS claims not applied: claims file is for csv {sha or '<none>'}")
    return NtrsOutcome(stored.claims, True, sha, None)
