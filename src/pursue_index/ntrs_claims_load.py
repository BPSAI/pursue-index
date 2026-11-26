"""Reading the stored NTRS claims, for the stages that resolve against them.

The coverage report reads ``data/provenance/ntrs-claims.json`` the same way it
reads the source catalogue: a missing file is not an error (a checkout that has
never run the NTRS search simply has no NTRS claims), and every stored claim is
rebuilt through :class:`~pursue_index.resolved_claim.ResolvedClaim`, so one the
constructor refuses is refused here too.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.resolved_claim import ResolvedClaim

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


def load_ntrs_claims(data: dict[str, Any]) -> NtrsClaims:
    """The positive claims held by a parsed ``ntrs-claims.json``, with their markers."""
    # Files written before the key was renamed carry ``source_manifest``.
    url = data.get("corpus_manifest_url", data.get("source_manifest"))
    return NtrsClaims(
        claims=[ResolvedClaim.from_dict(row) for row in data.get("claims", [])],
        csv_sha256=data.get("csv_sha256"),
        corpus_manifest_url=url,
    )


def read_ntrs_claims(repo_root: Path) -> NtrsClaims | None:
    """Load the tracked NTRS claims under ``repo_root``, or ``None`` if absent."""
    path = repo_root / NTRS_CLAIMS_PATH
    if not path.exists():
        return None
    return load_ntrs_claims(json.loads(path.read_text()))


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
    stored = read_ntrs_claims(repo_root)
    if stored is None:
        return NtrsOutcome([], False, None, None)
    sha = stored.csv_sha256 or None
    if sha is None or sha != manifest.get("csv_sha256"):
        return NtrsOutcome([], False, sha, f"NTRS claims not applied: claims file is for csv {sha or '<none>'}")
    return NtrsOutcome(stored.claims, True, sha, None)
