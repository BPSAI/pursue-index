"""Reading the stored NTRS claims, for the stages that resolve against them.

The coverage report reads ``data/provenance/ntrs-claims.json`` the same way it
reads the source catalogue: a missing file is not an error (a checkout that has
never run the NTRS search simply has no NTRS claims), and every stored claim is
rebuilt through :class:`~pursue_index.resolved_claim.ResolvedClaim`, so one the
constructor refuses is refused here too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pursue_index.resolved_claim import ResolvedClaim

__all__ = ["NTRS_CLAIMS_PATH", "load_ntrs_claims", "read_ntrs_claims"]

NTRS_CLAIMS_PATH = Path("data") / "provenance" / "ntrs-claims.json"


def load_ntrs_claims(data: dict[str, Any]) -> list[ResolvedClaim]:
    """The positive claims held by a parsed ``ntrs-claims.json``."""
    return [ResolvedClaim.from_dict(row) for row in data.get("claims", [])]


def read_ntrs_claims(repo_root: Path) -> list[ResolvedClaim]:
    """Load the tracked NTRS claims under ``repo_root``, or none if absent."""
    path = repo_root / NTRS_CLAIMS_PATH
    if not path.exists():
        return []
    return load_ntrs_claims(json.loads(path.read_text()))


class StaleNtrsClaimsError(ValueError):
    """Stub."""


def claims_for_manifest(repo_root: Path, manifest: dict[str, Any]) -> list[ResolvedClaim]:
    """Stub."""
    return []
