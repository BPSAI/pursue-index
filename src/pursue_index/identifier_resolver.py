"""Resolve card identifiers to typed provenance claims (spec §6, PV1.5).

The resolver takes the identifiers extracted by
:mod:`pursue_index.identifiers` and turns each into a
:class:`~pursue_index.resolved_claim.ResolvedClaim` — but **only when it
resolves to a real artifact**. Three resolution sources, none of them a search
snippet:

* **CIA CREST.** A ``CIA-RDP…`` ID resolves by a public, deterministic rule:
  the document lives at ``cia.gov/readingroom/document/<id>`` and the CREST
  collection was published online on 2017-01-17 (:data:`CREST_ONLINE_RELEASE`,
  a widely reported public fact). That yields a dated ``previously_released``
  claim without a network call.
* **The catalogue.** FBI, Blue Book and other identifiers resolve against the
  PV1.4 sitemap catalogue (:class:`~pursue_index.source_index.SourceEntry`): a
  match on filename/URL gives the artifact and an ``http_last_modified`` date.
  No ``Last-Modified`` header means no honest date, so that entry is skipped.
* **The government description.** COMETA-style content that is public but whose
  *specific record's* release is unestablished emits
  ``content_previously_published`` (spec §6c), read from the highest-authority
  source — the government's own CSV wording, via PV1.2's Tier-0 detector.

Two lines the resolver never crosses:

* An identifier match against a **subset of an omnibus file** never emits
  ``previously_released`` — it is downgraded to ``previously_released_in_part``
  and flagged for later page-image comparison. Matching a file number does not
  prove *these* pages were in the prior release.
* A claim is only emitted for a resolved artifact; nothing is inferred from a
  search-engine snippet.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from pursue_index.identifiers import Identifier, IdentifierKind, extract_identifiers
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.source_index import OUTPUT_PATH as CATALOGUE_PATH
from pursue_index.source_index import SourceEntry
from pursue_index.tier0_sweep import detect_claim as detect_tier0_claim

__all__ = [
    "CREST_ONLINE_RELEASE",
    "OUTPUT_PATH",
    "build_output",
    "is_omnibus_subset",
    "main",
    "resolve_against_catalogue",
    "resolve_card",
    "resolve_content_published",
    "resolve_crest",
]

#: Tracked output artifact (under ``data/``, never an ignored directory).
OUTPUT_PATH = Path("data") / "provenance" / "identifier-claims.json"

#: The CIA published the full CREST collection online on this date — a stated,
#: public publisher date every genuine ``CIA-RDP…`` document inherits.
CREST_ONLINE_RELEASE = date(2017, 1, 17)

_SCHEMA = "identifier-resolver-claims/v1"

# A card that is a numbered *section* / *part* of a larger file, or whose own
# description concedes it is partial, is an omnibus subset.
_OMNIBUS_SECTION_RE = re.compile(r"(?<![a-z])(?:section|part)[\s_]*\d+", re.IGNORECASE)
_OMNIBUS_PHRASES = ("some pages missing", "partially posted", "partial release")


def _value_pattern(value: str) -> re.Pattern[str] | None:
    """A boundary-delimited pattern for an identifier, tolerant of separators.

    ``62-HQ-83894`` matches ``62_hq_83894`` and ``62 hq 83894`` but the whole
    token must be bounded by non-alphanumerics — a bare number like ``10073``
    never matches inside ``2010073`` or ``v10073x``. This keeps a short case /
    NAID number from substring-matching an unrelated catalogue URL and emitting
    a false citation on a citable archive.
    """
    runs = re.findall(r"[a-z0-9]+", value.lower())
    if not runs:
        return None
    body = r"[-_\s]*".join(re.escape(run) for run in runs)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _parse_http_date(value: str | None) -> date | None:
    """Parse an HTTP ``Last-Modified`` header to a date, or ``None``."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def is_omnibus_subset(card: dict[str, Any]) -> bool:
    """True iff the card is a subset of a larger (omnibus) file."""
    title = str(card.get("title") or "")
    filename = str(card.get("asset_filename") or "")
    description = str(card.get("description") or "").lower()
    if _OMNIBUS_SECTION_RE.search(title) or _OMNIBUS_SECTION_RE.search(filename):
        return True
    return any(phrase in description for phrase in _OMNIBUS_PHRASES)


def resolve_crest(card: dict[str, Any], ident: Identifier) -> ResolvedClaim:
    """Resolve a CIA CREST ID to its readingroom artifact (public rule)."""
    return ResolvedClaim(
        card_id=str(card.get("card_id") or ""),
        tier=ProvenanceTier.PREVIOUSLY_RELEASED,
        source=ResolutionSource.KNOWN_ARCHIVE,
        identifier_kind=ident.kind.value,
        identifier_value=ident.value,
        artifact_url=f"https://www.cia.gov/readingroom/document/{ident.value.lower()}",
        established_date=CREST_ONLINE_RELEASE,
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def _entry_matches(value: str, entry: SourceEntry) -> bool:
    pattern = _value_pattern(value)
    if pattern is None:
        return False
    haystack = f"{entry.url}\n{entry.filename}".lower()
    return pattern.search(haystack) is not None


def resolve_against_catalogue(
    card: dict[str, Any], ident: Identifier, catalogue: Sequence[SourceEntry]
) -> ResolvedClaim | None:
    """Resolve an identifier against the PV1.4 catalogue, or ``None``.

    A match needs a datable ``Last-Modified``; without one there is no honest
    establishing date, so the entry is skipped rather than dated by a guess.
    """
    for entry in catalogue:
        if not _entry_matches(ident.value, entry):
            continue
        established = _parse_http_date(entry.last_modified)
        if established is None:
            continue
        return ResolvedClaim(
            card_id=str(card.get("card_id") or ""),
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            source=ResolutionSource.CATALOGUE,
            identifier_kind=ident.kind.value,
            identifier_value=ident.value,
            artifact_url=entry.url,
            established_date=established,
            date_basis=DateBasis.HTTP_LAST_MODIFIED,
        )
    return None


def resolve_content_published(card: dict[str, Any]) -> ResolvedClaim | None:
    """Emit a ``content_previously_published`` claim from the government wording.

    Uses PV1.2's Tier-0 detector: only when the government's own description
    concedes the *content* was previously published (the COMETA case, spec §6c)
    — never that *this record* was released.
    """
    tier0 = detect_tier0_claim(card)
    if tier0 is None or tier0.tier is not ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED:
        return None
    return ResolvedClaim(
        card_id=str(card.get("card_id") or ""),
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.GOVERNMENT_DESCRIPTION,
        prior_publication=tier0.prior_source,
        established_date=tier0.stated_date,
        date_basis=tier0.date_basis,
    )


def _apply_omnibus_gate(claim: ResolvedClaim, card: dict[str, Any]) -> ResolvedClaim:
    """Downgrade a whole-file ``previously_released`` on an omnibus subset."""
    if claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED and is_omnibus_subset(card):
        return replace(
            claim,
            tier=ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
            needs_page_image_comparison=True,
        )
    return claim


def _resolve_identifier(
    card: dict[str, Any], ident: Identifier, catalogue: Sequence[SourceEntry], enable_crest: bool
) -> ResolvedClaim | None:
    if ident.kind is IdentifierKind.CIA_CREST and enable_crest:
        return resolve_crest(card, ident)
    return resolve_against_catalogue(card, ident, catalogue)


def resolve_card(
    card: dict[str, Any],
    catalogue: Sequence[SourceEntry] = (),
    enable_crest: bool = True,
) -> list[ResolvedClaim]:
    """Resolve every identifier on a card to the claims it supports."""
    claims: list[ResolvedClaim] = []
    seen: set[tuple[str, str, str]] = set()
    content = resolve_content_published(card)
    if content is not None:
        claims.append(content)
    for ident in extract_identifiers(card):
        claim = _resolve_identifier(card, ident, catalogue, enable_crest)
        if claim is None:
            continue
        claim = _apply_omnibus_gate(claim, card)
        key = (claim.tier.value, claim.artifact_url, claim.identifier_value)
        if key in seen:
            continue
        seen.add(key)
        claims.append(claim)
    return claims


def build_output(
    manifest: dict[str, Any], claims: Sequence[ResolvedClaim], catalogue_entries: int
) -> dict[str, Any]:
    """Assemble the tracked artifact: resolver provenance + the claims."""
    return {
        "schema": _SCHEMA,
        "source_manifest": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "catalogue_entries": catalogue_entries,
        "card_count": len(manifest.get("cards", [])),
        "claim_count": len(claims),
        "tier_counts": dict(Counter(c.tier.value for c in claims)),
        "needs_page_image_comparison": sum(1 for c in claims if c.needs_page_image_comparison),
        "claims": [c.to_dict() for c in claims],
    }


def _load_catalogue(path: Path) -> list[SourceEntry]:
    """Load PV1.4 catalogue entries if the artifact exists, else empty."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [SourceEntry.from_dict(row) for row in data.get("entries", [])]


def main() -> int:
    """CLI: resolve ``data/manifests/latest.json`` -> the tracked artifact.

    Resolves against the PV1.4 catalogue when ``source-index.json`` is present;
    CREST and content-published resolutions need no catalogue, so COMETA still
    resolves in a clean checkout that has never run the (live) catalogue build.
    """
    repo_root = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo_root / "data" / "manifests" / "latest.json").read_text())
    catalogue = _load_catalogue(repo_root / CATALOGUE_PATH)
    claims: list[ResolvedClaim] = []
    for card in manifest.get("cards", []):
        claims.extend(resolve_card(card, catalogue=catalogue))
    out_path = repo_root / OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build_output(manifest, claims, len(catalogue)), indent=2) + "\n")
    print(f"identifier resolver: {len(claims)} claim(s) from {len(manifest.get('cards', []))} cards")
    print(f"  catalogue entries: {len(catalogue)}")
    print(f"  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
