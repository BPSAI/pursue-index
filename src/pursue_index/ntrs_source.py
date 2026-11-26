"""NASA NTRS metadata search as a provenance source for unresolved NASA cards.

NTRS (the NASA Technical Reports Server) publishes metadata for NASA documents,
including when each record was distributed. For the NASA cards the coverage
report leaves unresolved, this stage searches NTRS by title and, where a record
is the same document by title, compares its date with the card's own PURSUE
release date (spec §5).

What it will and will not say:

* **A positive claim needs a strictly earlier date.** A matching record counts
  only if its established date is before the card's ``release_date``. The date
  is NTRS ``distributionDate`` (``ntrs_distribution_date``), falling back to
  ``created`` (``ntrs_created_date``). ``publicationDate`` is the *document's*
  own date — Apollo-era transcripts carry 1969 — never when a copy became
  public, so it is never used.
* **The tier is** ``content_previously_published``. A title match shows the
  content is public, not that this specific record was (spec §6c).
* **Everything else is a search record.** A match dated on or after the release
  is evidence that every located copy post-dates it; no match is a search that
  found no copy. Neither is a statement about novelty, and absence of a prior
  release stays unestablished.

Pure matching and claim rules over an already-fetched response, plus a thin CLI:
``python -m pursue_index.ntrs_source``.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.atomic_text import write_text_atomic
from pursue_index.catalogue_dates import card_release_date
from pursue_index.catalogue_load import load_catalogue
from pursue_index.ntrs_fetch import NtrsFetcher, NtrsFetchError, default_get, load_ntrs_hosts
from pursue_index.ntrs_match import (
    MATCH_THRESHOLD,
    MIN_SHARED_TOKENS,
    matched_copies,
    normalize_query,
    title_matches,
    token_set_ratio,
    utc_today,
)
from pursue_index.paths import repo_root as _resolve_repo_root
from pursue_index.provenance import NO_PRIOR_RELEASE_DISCLAIMER, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.row_key import row_keys
from pursue_index.source_index import SourceEntry

__all__ = [
    "MATCH_THRESHOLD",
    "MIN_SHARED_TOKENS",
    "OUTPUT_PATH",
    "SCHEMA",
    "CardSearch",
    "build_output",
    "evaluate_card",
    "main",
    "normalize_query",
    "run_searches",
    "title_matches",
    "token_set_ratio",
    "unresolved_nasa_rows",
    "write_output",
]

OUTPUT_PATH = Path("data") / "provenance" / "ntrs-claims.json"
SCHEMA = "ntrs-claims/v2"
SOURCE_LABEL = "NASA NTRS"

RESULT_CLAIM = "claim"
RESULT_POST_DATING = "post_dating_copy_found"
RESULT_NO_COPY = "no_copy_found"
RESULT_UNDATED = "match_undated"
RESULT_NO_RELEASE_DATE = "release_date_unreadable"
RESULT_NOT_SEARCHED = "not_searched_empty_title"

_NOTES = {
    RESULT_CLAIM: "a record with this title was distributed before the card's release date",
    RESULT_POST_DATING: "every located copy is dated on or after the card's release date",
    RESULT_NO_COPY: f"this search found no copy; {NO_PRIOR_RELEASE_DISCLAIMER}",
    RESULT_UNDATED: "a record matched by title but carries no usable date; no claim made",
    RESULT_NO_RELEASE_DATE: "the card's release date is unreadable, so no comparison was made",
    RESULT_NOT_SEARCHED: "the title is empty after normalisation, so nothing was searched",
}

@dataclass(frozen=True)
class CardSearch:
    """One card's search: what was asked, when, and what it came to."""

    card_id: str
    query: str
    searched_date: date
    result: str
    claim: ResolvedClaim | None = None
    copies: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    row_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "row_key": self.row_key,
            "source": SOURCE_LABEL,
            "query": self.query,
            "searched_date": self.searched_date.isoformat(),
            "result": self.result,
            "note": _NOTES[self.result],
            "copies": list(self.copies),
        }


def evaluate_card(
    card: dict[str, Any], response: dict[str, Any], searched_date: date, row_key: str
) -> CardSearch:
    """Turn one search response into the card's claim or search record."""
    card_id = str(card.get("card_id") or "")
    query = normalize_query(str(card.get("title") or ""))
    copies = matched_copies(str(card.get("title") or ""), response)
    rows = tuple(c.to_dict() for c in copies)

    def record(result: str, claim: ResolvedClaim | None = None) -> CardSearch:
        return CardSearch(card_id, query, searched_date, result, claim, rows, row_key)

    if not copies:
        return record(RESULT_NO_COPY)
    released = card_release_date(card)
    if released is None:
        return record(RESULT_NO_RELEASE_DATE)
    prior = [c for c in copies if c.established is not None and c.established < released]
    if prior:
        best = min(prior, key=lambda c: (c.established, c.ntrs_id))  # type: ignore[type-var]
        claim = ResolvedClaim(
            card_id=card_id,
            row_key=row_key,
            tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
            source=ResolutionSource.NTRS_METADATA,
            identifier_kind="ntrs_citation_id",
            identifier_value=best.ntrs_id,
            artifact_url=best.url,
            established_date=best.established,
            date_basis=best.basis,
        )
        return record(RESULT_CLAIM, claim)
    if any(c.established is not None for c in copies):
        return record(RESULT_POST_DATING)
    return record(RESULT_UNDATED)


def unresolved_nasa_rows(
    manifest: dict[str, Any], catalogue: Sequence[SourceEntry] = ()
) -> list[tuple[str, dict[str, Any]]]:
    """The NASA rows the coverage report leaves unresolved, as (row_key, card), in manifest order."""
    report = build_report(manifest, catalogue)
    wanted = {o.row_key for o in report.unresolved_cards() if o.agency.strip().casefold() == "nasa"}
    cards = manifest.get("cards", [])
    return [(key, card) for key, card in zip(row_keys(cards), cards, strict=True) if key in wanted]


def run_searches(
    manifest: dict[str, Any],
    fetcher: NtrsFetcher,
    searched_date: date,
    catalogue: Sequence[SourceEntry] = (),
) -> list[CardSearch]:
    """Search NTRS once per unresolved NASA card. A fetch abort propagates."""
    searches: list[CardSearch] = []
    for key, card in unresolved_nasa_rows(manifest, catalogue):
        query = normalize_query(str(card.get("title") or ""))
        if not query:
            card_id = str(card.get("card_id") or "")
            searches.append(CardSearch(card_id, query, searched_date, RESULT_NOT_SEARCHED, row_key=key))
            continue
        searches.append(evaluate_card(card, fetcher.search(query), searched_date, key))
    return searches


def build_output(
    manifest: dict[str, Any], searches: Sequence[CardSearch], fetch_counts: dict[str, Any]
) -> dict[str, Any]:
    """The tracked artifact: the claims, and the record of every search."""
    claims = [s.claim for s in searches if s.claim is not None]
    return {
        "schema": SCHEMA,
        "source": SOURCE_LABEL,
        "corpus_manifest_url": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "card_row_count": len(manifest.get("cards", [])),
        "searched_count": len(searches),
        "fetch": fetch_counts,
        "result_counts": dict(sorted(Counter(s.result for s in searches).items())),
        "claim_count": len(claims),
        "claims": [c.to_dict() for c in claims],
        "searches": [s.to_dict() for s in searches],
    }


def write_output(repo_root: Path, output: dict[str, Any]) -> Path:
    """Write the artifact under ``repo_root`` atomically and return its path.

    It goes to a temp file in the same directory, then ``os.replace``; on any
    failure the previous file is untouched and no temp file is left.
    """
    out_path = repo_root / OUTPUT_PATH
    write_text_atomic(out_path, json.dumps(output, indent=2) + "\n")
    return out_path


def run(repo_root: Path, fetcher: NtrsFetcher, searched_date: date) -> int:
    """Search, write the artifact, report. Any abort writes nothing."""
    manifest = json.loads((repo_root / "data" / "manifests" / "latest.json").read_text())
    catalogue = load_catalogue(repo_root)
    try:
        searches = run_searches(manifest, fetcher, searched_date, catalogue.entries)
    except NtrsFetchError as exc:
        kept = "; previous file kept" if (repo_root / OUTPUT_PATH).exists() else ""
        print(f"ntrs-source: aborted — {exc}\n  fetch: {fetcher.fetch_counts()}\n  nothing written{kept}")
        return 1
    out_path = write_output(repo_root, build_output(manifest, searches, fetcher.fetch_counts()))
    claims = sum(1 for s in searches if s.claim is not None)
    print(f"ntrs-source: {len(searches)} card(s) searched, {claims} claim(s)")
    print(f"  fetch: {fetcher.fetch_counts()}\n  wrote {out_path.relative_to(repo_root)}")
    return 0


def main() -> int:
    """CLI: search NTRS metadata for unresolved NASA cards → the tracked artifact."""
    repo_root = _resolve_repo_root()
    try:
        hosts = load_ntrs_hosts(repo_root)
    except NtrsFetchError as exc:
        print(f"ntrs-source: aborted — {exc}")
        return 1
    return run(repo_root, NtrsFetcher(get=default_get, hosts=hosts), utc_today())


if __name__ == "__main__":
    sys.exit(main())
