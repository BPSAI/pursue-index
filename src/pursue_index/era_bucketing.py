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

Headline counts (``era_counts``, ``no_prior_release_count``) are per source file:
rows sharing a ``card_id`` are one file with one era, and a file whose rows still
disagree is counted once under ``undated``. The per-row tallies sit beside them as
``era_row_counts`` and ``no_prior_release_row_count``; the triage list and the
``cards`` list stay one entry per manifest row.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pursue_index.atomic_text import write_text_atomic
from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.claim_precedence import PositiveClaim, unkeyed_claims
from pursue_index.era_dates import ResolvedEraDate, resolve_era_date
from pursue_index.era_models import (
    DOCUMENT_DATE_FIELDS,
    ERA_LABELS,
    CardEra,
    Era,
    EraNoPriorRelease,
    era_for_year,
    era_rationale,
)
from pursue_index.era_reconcile import FileEras, reconcile_file_eras
from pursue_index.era_supersession import SUPERSEDED_REASON, superseded_entry
from pursue_index.era_triage import triage_entry as _triage_entry
from pursue_index.file_basis import effective_claims, tallies
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

_SCHEMA = "era-agency-buckets/v1"


def _era_of(resolved: ResolvedEraDate) -> Era:
    """Map a resolved date to an era; release-only / no-date → ``UNDATED``."""
    if resolved.year is None or resolved.source_field not in DOCUMENT_DATE_FIELDS:
        return Era.UNDATED
    return era_for_year(resolved.year)


def _identifier(card: dict[str, Any]) -> str:
    """The most stable identifier available for a card."""
    return str(card.get("asset_filename") or card.get("title") or card.get("card_id") or "")


def classify_rows(cards: Sequence[dict[str, Any]]) -> FileEras:
    """Classify every row, key it, and reconcile each file to one era."""
    return reconcile_file_eras(cards, [classify_card(card) for card in cards])


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


def _no_prior_release(card_era: CardEra) -> EraNoPriorRelease:
    """Build the 2015+ negative from an already-classified card.

    A MODERN card always carries a year read from a document-date field. Raising
    rather than asserting keeps that invariant enforced under ``python -O``,
    where asserts are stripped and a negative could otherwise be built from a
    missing year.
    """
    if card_era.year is None or card_era.date_source is None:
        raise ValueError(
            f"card {card_era.card_id!r} is bucketed {card_era.era.value} but carries "
            "no document date; a no-prior-release record needs the year it rests on"
        )
    rationale = era_rationale(card_era.year, card_era.date_source)
    if card_era.era_reconciled_from:
        rationale += (
            f" This row names the same source file as {card_era.era_reconciled_from}, "
            "whose date it takes."
        )
    return EraNoPriorRelease(
        card_id=card_era.card_id,
        identifier=card_era.identifier,
        title=card_era.title,
        agency=card_era.agency,
        established_year=card_era.year,
        date_source=card_era.date_source,
        established_date=card_era.raw_date or str(card_era.year),
        rationale=rationale,
        row_key=card_era.row_key,
        era_reconciled_from=card_era.era_reconciled_from,
    )


@dataclass
class BucketResult:
    """The full outcome: per-card assignments, 2015+ negatives, triage, counts.

    ``era_counts`` and ``no_prior_release_files`` are per source file (rows that
    share a ``card_id`` are one file; a file whose rows disagree on era is counted
    once under ``undated``). ``era_row_counts`` is the same tally per manifest row.
    ``claims_without_row_key`` is how many loaded claims named no row and so
    resolved nothing.

    ``superseded`` holds the modern cards that would have taken a negative but
    carry a positive prior-release claim instead — the suppression is published,
    not silent.
    """

    cards: list[CardEra]
    claims: list[EraNoPriorRelease]
    triage: list[dict[str, Any]]
    era_counts: dict[str, int] = field(default_factory=dict)
    era_row_counts: dict[str, int] = field(default_factory=dict)
    file_count: int = 0
    no_prior_release_files: int = 0
    claims_without_row_key: int = 0
    agency_counts: dict[str, int] = field(default_factory=dict)
    superseded: list[dict[str, Any]] = field(default_factory=list)


def _modern_outcome(
    card_era: CardEra, claim: PositiveClaim | None
) -> tuple[EraNoPriorRelease | None, dict[str, Any] | None]:
    """For one modern card: its negative, or the claim row that supersedes it."""
    if claim is not None:
        return None, superseded_entry(card_era, claim)
    return _no_prior_release(card_era), None


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
    reconciled = classify_rows(raw_cards)
    classified = reconciled.cards
    claims: list[EraNoPriorRelease] = []
    superseded: list[dict[str, Any]] = []
    triage: list[dict[str, Any]] = []
    row_claims = effective_claims(raw_cards, classified, catalogue, extra_claims)
    for card_era, card, row_claim in zip(classified, raw_cards, row_claims, strict=True):
        if card_era.era is Era.MODERN_OPERATIONAL:
            claim, row = _modern_outcome(card_era, row_claim)
            claims.extend([claim] if claim is not None else [])
            superseded.extend([row] if row is not None else [])
        elif card_era.era is Era.UNDATED:
            triage.append(_triage_entry(card_era, card, reconciled.conflicts.get(card_era.row_key)))
    era_counts, era_row_counts, agency_counts = tallies(classified)
    return BucketResult(
        cards=classified,
        claims=claims,
        triage=triage,
        era_counts=era_counts,
        era_row_counts=era_row_counts,
        file_count=sum(era_counts.values()),
        no_prior_release_files=len({c.card_id for c in claims}),
        claims_without_row_key=unkeyed_claims(extra_claims),
        agency_counts=agency_counts,
        superseded=superseded,
    )


def _reconciliation(era_counts: dict[str, int]) -> dict[str, Any]:
    """Compare current-manifest era counts against the §4a reference table."""
    deltas = {key: era_counts.get(key, 0) - ref for key, ref in REFERENCE_4A.items()}
    return {
        "reference_4a": REFERENCE_4A,
        "current": {key: era_counts.get(key, 0) for key in REFERENCE_4A},
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
        "card_count": len(result.cards),
        "catalogue_entries": len(loaded.entries),
        "catalogue_rows_dropped": {
            "count": loaded.dropped_rows,
            "reason": INVALID_URL_EXCLUSION_REASON,
        },
        "file_count": result.file_count,
        "era_counts": result.era_counts,
        "era_row_counts": result.era_row_counts,
        "agency_counts": result.agency_counts,
        "reconciliation_4a": _reconciliation(result.era_counts),
        "no_prior_release_count": result.no_prior_release_files,
        "no_prior_release_row_count": len(result.claims),
        "claims_without_row_key": result.claims_without_row_key,
        "no_prior_release": [claim.to_dict() for claim in result.claims],
        "superseded_by_claim_count": len(result.superseded),
        "superseded_by_claim": result.superseded,
        "undated_triage_count": len(result.triage),
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
    labelled = ", ".join(f"{ERA_LABELS[era]}={result.era_counts[era.value]}" for era in Era)
    print(f"era bucketing: {len(result.cards)} cards -> {labelled}")
    print(f"  {result.file_count} files / {len(result.cards)} rows; {result.no_prior_release_files} files ({len(result.claims)} rows) no_prior_release (2015+)")
    print(f"  {len(result.triage)} undated rows (triage); {len(result.superseded)} rows superseded by a prior-release claim; {result.claims_without_row_key} claim(s) without a row_key")
    print(f"  catalogue: {len(catalogue.entries)} entries, {catalogue.dropped_rows} row(s) skipped\n  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
