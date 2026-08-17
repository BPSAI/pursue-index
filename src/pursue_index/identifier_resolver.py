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
  match on filename/URL, inside the collection that issues the identifier,
  gives the artifact, and the row's own last-modified value gives the date,
  read in the syntax the row's ``date_basis`` names and reported under that
  same basis. A row that supplies no readable date supplies
  no honest one either, so it is skipped — and a dated row evidences a *prior*
  release only when it falls strictly before the card's own release date.
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
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from pursue_index.catalogue_dates import card_release_date, entry_established_date
from pursue_index.catalogue_load import load_catalogue
from pursue_index.identifier_collections import entry_in_identifier_collection
from pursue_index.identifiers import Identifier, IdentifierKind, extract_identifiers
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.source_index import INVALID_URL_EXCLUSION_REASON, SourceEntry
from pursue_index.tier0_sweep import detect_claim as detect_tier0_claim

__all__ = [
    "CREST_ONLINE_RELEASE",
    "MIN_NUMERIC_IDENTIFIER_DIGITS",
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

#: A purely-numeric identifier shorter than this resolves nothing. A short bare
#: number is indistinguishable from the incidental numerals archives put in paths
#: and filenames — a year, a box, a page count, a batch — so it cannot name a
#: document on its own. The floor does cost real matches: Project Blue Book case
#: numbers run from 1 to about 12,618, so most of that range is four digits or
#: fewer and falls below it. That is the trade this resolver chooses, because a
#: claim cites a specific artifact by URL: a missed match leaves a card for a
#: later phase, while a wrong one publishes a citation to a document that has
#: nothing to do with the card.
MIN_NUMERIC_IDENTIFIER_DIGITS = 5

#: Identifier families whose values are bare numbers, and so carry no structure
#: that could distinguish them from an archive's own numbering.
_NUMERIC_IDENTIFIER_KINDS = frozenset({IdentifierKind.BLUE_BOOK_CASE, IdentifierKind.NAID})

_SCHEMA = "identifier-resolver-claims/v1"

# A card that is a numbered *section* / *part* of a larger file, or whose own
# description concedes it is partial, is an omnibus subset.
_OMNIBUS_SECTION_RE = re.compile(r"(?<![a-z])(?:section|part)[\s_]*\d+", re.IGNORECASE)
_OMNIBUS_PHRASES = ("some pages missing", "partially posted", "partial release")


def _too_short_to_identify(value: str) -> bool:
    """True for a purely-numeric value too short to name a document.

    A bounded-token match still lets a short number match freely when it *is*
    its own token — ``case 14`` against a ``/2020/14/`` path segment, ``NAID
    413`` against ``rpt-413.pdf``. Archive paths and filenames are full of short
    numerals that mean something else entirely, and a bare number carries no
    structure to tell the two apart, so below
    :data:`MIN_NUMERIC_IDENTIFIER_DIGITS` a numeric value resolves nothing.
    """
    digits = re.sub(r"[^0-9]", "", value)
    return digits == re.sub(r"[^a-z0-9]", "", value.lower()) and len(digits) < MIN_NUMERIC_IDENTIFIER_DIGITS


def _value_pattern(value: str) -> re.Pattern[str] | None:
    """A boundary-delimited pattern for an identifier, tolerant of separators.

    ``62-HQ-83894`` matches ``62_hq_83894`` and ``62 hq 83894`` but the whole
    token must be bounded by non-alphanumerics — a bare number like ``10073``
    never matches inside ``2010073`` or ``v10073x``. This keeps a short case /
    NAID number from substring-matching an unrelated catalogue URL and emitting
    a false citation on a citable archive.
    """
    if _too_short_to_identify(value):
        return None
    runs = re.findall(r"[a-z0-9]+", value.lower())
    if not runs:
        return None
    body = r"[-_\s]*".join(re.escape(run) for run in runs)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


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


def _match_targets(ident: Identifier, entry: SourceEntry) -> tuple[str, ...]:
    """The parts of a catalogue entry that can name the document it points to.

    The filename stem always can: it is the archive's name for that document.
    Whether a *directory* can depends on the identifier family.

    A structured file number — ``62-HQ-83894``, ``CIA-RDP81-…`` — carries its
    own agency and series, so it means the same thing wherever an archive writes
    it. An archive that gives such a number a directory of its own has named the
    file, and the documents filed directly beneath it are that file; a generic
    filename like ``cover-letter.pdf`` describes the page rather than the case,
    so refusing the directory would mean refusing a match the archive stated.
    Only the *last* directory counts: a segment further up names the collection
    the document sits in, not the document.

    A purely-numeric identifier gets no such reach. Archive paths number years,
    boxes and batches (``/2020/14/``), so a bare number standing as a directory
    is as likely to be one of those as it is to be a case number — and there is
    nothing in the value to tell them apart. For those, the filename is the
    only evidence.
    """
    stem = PurePosixPath(entry.filename).stem.lower()
    if ident.kind in _NUMERIC_IDENTIFIER_KINDS:
        return (stem,)
    parents = PurePosixPath(urlparse(entry.url).path).parent
    return (stem, parents.name.lower())


def _entry_matches(ident: Identifier, entry: SourceEntry) -> bool:
    """True iff the catalogue entry is the archive naming ``ident``'s document.

    Both questions have to answer yes: the row has to sit in an archive that
    could hold this identifier's family at all (a bare case number is a case
    number only inside the collection that issues it), and the identifier has
    to name the row's document there.
    """
    if not entry_in_identifier_collection(ident, entry):
        return False
    pattern = _value_pattern(ident.value)
    if pattern is None:
        return False
    return any(target and pattern.search(target) is not None for target in _match_targets(ident, entry))


def resolve_against_catalogue(
    card: dict[str, Any], ident: Identifier, catalogue: Sequence[SourceEntry]
) -> ResolvedClaim | None:
    """Resolve an identifier against the PV1.4 catalogue, or ``None``.

    A match needs a date it can read from the row, in the syntax the row's own
    basis names; without one there is no honest establishing date, so the entry
    is skipped rather than dated by a guess. The claim reports that same basis,
    because a claim states the footing it rests on rather than a nearby one.

    A dated match also has to be *prior*. The catalogue is enumerated live from
    a third-party host, so it holds rows of every vintage in whatever order the
    sitemaps list them — including copies of material published after the
    release under examination. Only a row dated strictly before the card's own
    release date evidences a release that came first; a row that is not is one
    candidate declined, and the search moves to the rest. A card whose release
    date cannot be read offers nothing to compare against, so catalogue
    evidence yields it no dated claim.

    A row the claim constructor refuses costs that row only: the search
    continues to the next entry. Rows are validated where they are built, so
    this is the layer beneath that — proportionality if one ever arrives
    unvalidated, since ``classify`` calls this across the whole corpus.
    """
    released = card_release_date(card)
    if released is None:
        return None
    for entry in catalogue:
        if not _entry_matches(ident, entry):
            continue
        established = entry_established_date(entry)
        if established is None or established >= released:
            continue
        try:
            return ResolvedClaim(
                card_id=str(card.get("card_id") or ""),
                tier=ProvenanceTier.PREVIOUSLY_RELEASED,
                source=ResolutionSource.CATALOGUE,
                identifier_kind=ident.kind.value,
                identifier_value=ident.value,
                artifact_url=entry.url,
                established_date=established,
                date_basis=entry.date_basis,
            )
        except ValueError:
            continue
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
    manifest: dict[str, Any],
    claims: Sequence[ResolvedClaim],
    catalogue_entries: int,
    catalogue_rows_dropped: int = 0,
) -> dict[str, Any]:
    """Assemble the tracked artifact: resolver provenance + the claims.

    ``catalogue_rows_dropped`` says how much of the stored catalogue could not
    be read. A resolver's output is only as complete as the surface it searched,
    so that figure travels in the artifact rather than only on the console that
    produced it.
    """
    return {
        "schema": _SCHEMA,
        "source_manifest": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "catalogue_entries": catalogue_entries,
        "catalogue_rows_dropped": {
            "count": catalogue_rows_dropped,
            "reason": INVALID_URL_EXCLUSION_REASON,
        },
        "card_count": len(manifest.get("cards", [])),
        "claim_count": len(claims),
        "tier_counts": dict(Counter(c.tier.value for c in claims)),
        "needs_page_image_comparison": sum(1 for c in claims if c.needs_page_image_comparison),
        "claims": [c.to_dict() for c in claims],
    }


def main() -> int:
    """CLI: resolve ``data/manifests/latest.json`` -> the tracked artifact.

    Resolves against the PV1.4 catalogue when ``source-index.json`` is present;
    CREST and content-published resolutions need no catalogue, so COMETA still
    resolves in a clean checkout that has never run the (live) catalogue build.
    The catalogue is read through the shared loader, so this artifact rests on
    exactly the rows the era pass and the coverage report rest on.
    """
    repo_root = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo_root / "data" / "manifests" / "latest.json").read_text())
    catalogue = load_catalogue(repo_root)
    claims: list[ResolvedClaim] = []
    for card in manifest.get("cards", []):
        claims.extend(resolve_card(card, catalogue=catalogue.entries))
    out_path = repo_root / OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output = build_output(manifest, claims, len(catalogue.entries), catalogue.dropped_rows)
    out_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"identifier resolver: {len(claims)} claim(s) from {len(manifest.get('cards', []))} cards")
    print(f"  catalogue entries: {len(catalogue.entries)}")
    print(f"  catalogue rows skipped: {catalogue.dropped_rows}")
    print(f"  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
