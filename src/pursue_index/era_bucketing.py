"""Era and agency bucketing (spec §4a / §5).

A record cannot appear in an archive assembled before it existed. Most of the
corpus is modern operational material — mission reports, range-fouler debriefs,
recent field-office sightings — for which no prior-release surface can exist.
This stage buckets every card by document era and agency and, for the 2015+
set, emits an :class:`~pursue_index.era_models.EraNoPriorRelease` record so that
"no prior release" is an *auditable* conclusion carrying its era rationale,
never a bare assertion.

Two honest restraints, both from the §5 doctrine:

* **``release_date`` is not a document era.** It is the war.gov publication date
  (≈2026 for every card). A card whose only date is ``release_date`` — or which
  has no date at all — is **undated** and is surfaced on an explicit triage
  list, never silently bucketed as 2015+.
* **Only the 2015+ set gets a negative.** The pre-2015 eras are the research
  surface (they *may* have a prior release); they are bucketed and counted but
  left for the Tier-0/1 resolvers. Emitting a negative for them would assert the
  very thing this spec refuses to assert.

The model lives in :mod:`pursue_index.era_models`; this module classifies,
aggregates, reconciles against the §4a reference table, and writes the tracked
artifact.

Schema units. ``row_key`` (``<card_id>#<n>``) is the per-row key; ``card_id`` names a
source file and is not unique upstream, since several rows can share one. A count
named ``*_row_count`` (or ``*_row_counts``) counts rows and equals the length of the
row array beside it. Every other count is per file: rows sharing a ``card_id`` are one
file, and a file has exactly one era: its undated rows take the era of its one dated
era-and-year (a file whose dated rows conflict is ``undated``). The route of a row and
of a file is :mod:`pursue_index.file_basis`'s. ``no_prior_release_file_count`` is the length of
``no_prior_release_files`` (one id per file); ``no_prior_release_rows`` is one record
per row, counted by ``no_prior_release_row_count``. The triage list, the superseded
list and ``cards`` stay one entry per manifest row. The §4a reference is a per-row
baseline, so the comparison reads ``era_row_counts``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pursue_index.atomic_text import write_text_atomic
from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.era_dates import ResolvedEraDate, resolve_era_date
from pursue_index.era_models import (
    DOCUMENT_DATE_FIELDS,
    ERA_LABELS,
    CardEra,
    Era,
    EraNoPriorRelease,
    era_for_year,
)
from pursue_index.era_negative import no_prior_release as _no_prior_release
from pursue_index.era_reconcile import FileEras, reconcile_file_eras
from pursue_index.era_supersession import SUPERSEDED_REASON, claim_resolved_entry, superseded_entry
from pursue_index.era_triage import triage_entry as _triage_entry
from pursue_index.file_basis import Route, RowBasis, assess, route_fields
from pursue_index.file_counts import count_fields
from pursue_index.ntrs_claims_load import resolve_ntrs_claims
from pursue_index.paths import repo_root as _resolve_repo_root
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.source_index import INVALID_URL_EXCLUSION_REASON, SourceEntry

__all__ = [
    "OUTPUT_PATH",
    "REFERENCE_4A",
    "SUPERSEDED_REASON",
    "BucketResult",
    "bucket",
    "build_output",
    "classify_card",
    "classify_reconciled",
    "classify_rows",
]

#: Tracked output artifact (under ``data/``, never an ignored directory).
OUTPUT_PATH = Path("data") / "provenance" / "era-buckets.json"

#: Spec §4a reference table (author's snapshot, 2026-08-06). Counts for the
#: *current* manifest are reconciled against this in :func:`build_output`.
REFERENCE_4A: dict[str, int] = {
    "2015_plus": 206,
    "1990_2014": 13,
    "1970_1989": 19,
    "pre_1970": 60,
    "undated": 36,
}

_SCHEMA = "era-agency-buckets/v2"


def _era_of(resolved: ResolvedEraDate) -> Era:
    """Map a resolved date to an era; release-only / no-date → ``UNDATED``."""
    if resolved.year is None or resolved.source_field not in DOCUMENT_DATE_FIELDS:
        return Era.UNDATED
    return era_for_year(resolved.year)


def _identifier(card: dict[str, Any]) -> str:
    """The most stable identifier available for a card."""
    return str(card.get("asset_filename") or card.get("title") or card.get("card_id") or "")


def classify_reconciled(cards: Sequence[dict[str, Any]]) -> FileEras:
    """Classify and key every row, then reconcile each file to one era."""
    return reconcile_file_eras(cards, [classify_card(card) for card in cards])


def classify_rows(cards: Sequence[dict[str, Any]]) -> list[CardEra]:
    """Classify every row, key it ``<card_id>#<n>``, and reconcile its file's era, in manifest order."""
    return classify_reconciled(cards).cards


def classify_card(card: dict[str, Any]) -> CardEra:
    """Assign a card its era (via the display-date precedence) and agency."""
    resolved = resolve_era_date(card)
    era = _era_of(resolved)
    # An undated card carries no date at all: release_date is a publication
    # date, never a document era, so it must not surface as year/source/raw.
    dated = era is not Era.UNDATED
    return CardEra(
        card_id=str(card.get("card_id") or ""),
        identifier=_identifier(card),
        title=str(card.get("title") or ""),
        agency=str(card.get("agency") or "").strip() or "Unknown",
        era=era,
        year=resolved.year if dated else None,
        date_source=resolved.source_field if dated else None,
        raw_date=resolved.raw if dated else None,
    )


@dataclass
class BucketResult:
    """The full outcome: per-card assignments, 2015+ negatives, triage, counts.

    ``era_file_counts`` and ``no_prior_release_files`` (the ids of the
    files holding a negative) are per source file; ``era_row_counts`` is the same
    tally per manifest row. ``unkeyed_claim_count`` is how many loaded claims
    named no row and so resolved nothing.

    ``superseded`` holds the modern cards that would have taken a negative but
    carry a positive prior-release claim instead — the suppression is published,
    not silent.
    """

    cards: list[CardEra]
    claims: list[EraNoPriorRelease]
    triage: list[dict[str, Any]]
    era_file_counts: dict[str, int] = field(default_factory=dict)
    era_row_counts: dict[str, int] = field(default_factory=dict)
    file_count: int = 0
    no_prior_release_files: list[str] = field(default_factory=list)
    unkeyed_claim_count: int = 0
    agency_file_counts: dict[str, int] = field(default_factory=dict)
    agency_row_counts: dict[str, int] = field(default_factory=dict)
    superseded: list[dict[str, Any]] = field(default_factory=list)
    claim_resolved: list[dict[str, Any]] = field(default_factory=list)
    file_route_counts: dict[str, int] = field(default_factory=dict)
    row_route_counts: dict[str, int] = field(default_factory=dict)
    partially_resolved_files: list[str] = field(default_factory=list)


def _inherited_conflict(row: RowBasis) -> str | None:
    """The date-conflict reason of a row that inherits its claim, else ``None``."""
    return row.conflict if row.inherited_from is not None else None


def bucket(
    manifest: dict[str, Any],
    catalogue: Sequence[SourceEntry] = (),
    extra_claims: Sequence[ResolvedClaim] = (),
) -> BucketResult:
    """Bucket every card by era and agency; emit 2015+ negatives + triage.

    A modern card whose claim chain asserts a positive prior release does not
    receive a negative: the claim is evidence the era inference would contradict.
    Those cards are listed in ``superseded`` with the claim that outranked them.

    ``catalogue`` is the same catalogue the coverage report resolves
    against, and it is passed to the same precedence helper. It is optional
    because the Tier-0 and CREST routes need none — but a card whose *only*
    positive claim is a catalogue match is exactly the card the two artifacts
    would describe differently if this stage were the one that could not see it.

    ``extra_claims`` are the claims from any further source (the NTRS claims),
    the same ones the coverage report receives: a positive claim wins even when
    the card is also a 2015+ document.
    """
    raw_cards = manifest.get("cards", [])
    reconciled = classify_reconciled(raw_cards)
    rows = assess(raw_cards, reconciled, catalogue, extra_claims)
    claims: list[EraNoPriorRelease] = []
    superseded: list[dict[str, Any]] = []
    claim_resolved: list[dict[str, Any]] = []
    triage: list[dict[str, Any]] = []
    for row, card in zip(rows, raw_cards, strict=True):
        card_era = row.era
        if row.route is Route.ERA:
            claims.append(_no_prior_release(card_era))
        elif row.route in (Route.CLAIM, Route.CLAIM_INHERITED):
            # A claim, own or inherited, resolves the row whatever its era: a modern row
            # is published as superseded; any other era (undated included) is listed as claim-resolved.
            if row.claim is None:
                continue
            if card_era.era is Era.MODERN_OPERATIONAL:
                superseded.append(superseded_entry(card_era, row.claim, row.inherited_from, _inherited_conflict(row)))
            else:
                claim_resolved.append(claim_resolved_entry(card_era, row.claim, row.inherited_from, _inherited_conflict(row)))
        elif row.conflict is not None:
            triage.append(_triage_entry(card_era, card, row.conflict))
        elif card_era.era is Era.UNDATED:
            triage.append(_triage_entry(card_era, card))
    counts = count_fields(reconciled.cards, claims, extra_claims, reconciled.conflicts)
    return BucketResult(reconciled.cards, claims, triage, superseded=superseded, claim_resolved=claim_resolved, **counts, **route_fields(rows))


def _reconciliation(era_row_counts: dict[str, int]) -> dict[str, Any]:
    """Compare current-manifest per-row era counts against the §4a reference table.

    ``REFERENCE_4A`` is a per-row baseline from an earlier corpus, so it is compared
    with the per-row counts (never the per-file ones).
    """
    deltas = {key: era_row_counts.get(key, 0) - ref for key, ref in REFERENCE_4A.items()}
    return {
        "unit": "rows",
        "reference_4a": REFERENCE_4A,
        "current": {key: era_row_counts.get(key, 0) for key in REFERENCE_4A},
        "delta": deltas,
        "matches_reference": all(delta == 0 for delta in deltas.values()),
        "note": (
            "Two causes account for the undated delta, and they are separate. "
            "(1) Display-date curation: §4a was computed against a manifest with "
            "that curation applied, and this manifest carries a curated "
            "display_date for only a handful of cards, so cards §4a dated via "
            "display_date surface here as triage. (2) Two-digit years: a "
            "two-digit year states no century, so this stage reads one through a "
            "pivot and accepts the result only when a four-digit year elsewhere "
            "on the same card states the same year — a card whose only date is "
            "an uncorroborated two-digit year is undated here for that reason "
            "rather than for the first. In both cases release_date (the war.gov "
            "publication date) is never used as a document era."
        ),
    }


def build_output(
    manifest: dict[str, Any], result: BucketResult, catalogue: LoadedCatalogue | None = None
) -> dict[str, Any]:
    """Assemble the tracked artifact: counts, reconciliation, negatives, triage.

    ``catalogue`` records the claim surface the negatives were decided against:
    how many rows were available, and how many the stored artifact held that
    could not be read. A negative rests on finding no claim, so how much was
    searched is part of the finding.
    """
    loaded = catalogue if catalogue is not None else LoadedCatalogue([], 0)
    return {
        "schema": _SCHEMA,
        "corpus_manifest_url": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "card_row_count": len(result.cards),
        "catalogue_entries": len(loaded.entries),
        "catalogue_rows_dropped": {
            "count": loaded.dropped_rows,
            "reason": INVALID_URL_EXCLUSION_REASON,
        },
        "file_count": result.file_count,
        "era_file_counts": result.era_file_counts,
        "era_row_counts": result.era_row_counts,
        "agency_file_counts": result.agency_file_counts,
        "agency_row_counts": result.agency_row_counts,
        "file_route_counts": result.file_route_counts,
        "row_route_counts": result.row_route_counts,
        "partially_resolved_file_count": len(result.partially_resolved_files),
        "partially_resolved_files": result.partially_resolved_files,
        "reconciliation_4a": _reconciliation(result.era_row_counts),
        "no_prior_release_file_count": len(result.no_prior_release_files),
        "no_prior_release_files": result.no_prior_release_files,
        "no_prior_release_row_count": len(result.claims),
        "unkeyed_claim_count": result.unkeyed_claim_count,
        "no_prior_release_rows": [claim.to_dict() for claim in result.claims],
        "superseded_by_claim_row_count": len(result.superseded),
        "superseded_by_claim": result.superseded,
        "claim_resolved_row_count": len(result.claim_resolved),
        "claim_resolved_rows": result.claim_resolved,
        "undated_triage_row_count": len(result.triage),
        "undated_triage": result.triage,
        "cards": [ce.to_dict() for ce in result.cards],
    }


def main() -> int:
    """CLI: bucket ``data/manifests/latest.json`` -> the tracked artifact.

    The catalogue is read through the shared loader, so this artifact rests on
    exactly the rows the coverage report and the identifier resolver rest on.
    """
    repo_root = _resolve_repo_root()
    manifest = json.loads((repo_root / "data" / "manifests" / "latest.json").read_text())
    catalogue = load_catalogue(repo_root)
    ntrs = resolve_ntrs_claims(repo_root, manifest)
    if ntrs.notice:
        print(ntrs.notice)
    result = bucket(manifest, catalogue.entries, ntrs.claims)
    out_path = repo_root / OUTPUT_PATH
    output = {**build_output(manifest, result, catalogue), **ntrs.summary_fields()}
    write_text_atomic(out_path, json.dumps(output, indent=2) + "\n")
    labelled = ", ".join(f"{ERA_LABELS[era]}={result.era_file_counts[era.value]}" for era in Era)
    print(f"era bucketing: {result.file_count} files / {len(result.cards)} rows -> {labelled} (files)")
    print(f"  routes, files: {result.file_route_counts}; rows: {result.row_route_counts}; {len(result.partially_resolved_files)} partially resolved file(s)")
    print(f"  {len(result.no_prior_release_files)} files ({len(result.claims)} rows) no_prior_release (2015+); {len(result.triage)} undated rows (triage)")
    print(f"  {len(result.superseded)} rows superseded by a prior-release claim; {len(result.claim_resolved)} other rows claim-resolved; {result.unkeyed_claim_count} claim(s) without a row_key")
    print(f"  catalogue: {len(catalogue.entries)} entries, {catalogue.dropped_rows} row(s) skipped\n  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
