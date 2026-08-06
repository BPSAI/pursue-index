"""Era and agency bucketing (spec §4a / §5, PV1.3).

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
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

__all__ = [
    "OUTPUT_PATH",
    "REFERENCE_4A",
    "BucketResult",
    "bucket",
    "build_output",
    "classify_card",
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


def classify_card(card: dict[str, Any]) -> CardEra:
    """Assign a card its era (via the display-date precedence) and agency."""
    resolved = resolve_era_date(card)
    return CardEra(
        card_id=str(card.get("card_id") or ""),
        identifier=_identifier(card),
        title=str(card.get("title") or ""),
        agency=str(card.get("agency") or "").strip() or "Unknown",
        era=_era_of(resolved),
        year=resolved.year,
        date_source=resolved.source_field,
        raw_date=resolved.raw,
    )


def _no_prior_release(card_era: CardEra) -> EraNoPriorRelease:
    """Build the 2015+ negative from an already-classified card."""
    assert card_era.year is not None and card_era.date_source is not None  # MODERN invariant
    return EraNoPriorRelease(
        card_id=card_era.card_id,
        identifier=card_era.identifier,
        title=card_era.title,
        agency=card_era.agency,
        established_year=card_era.year,
        date_source=card_era.date_source,
        established_date=card_era.raw_date or str(card_era.year),
        rationale=era_rationale(card_era.year, card_era.date_source),
    )


def _triage_entry(card_era: CardEra, card: dict[str, Any]) -> dict[str, Any]:
    """An explicit triage row for an undated card — never silently bucketed."""
    reason = (
        "only a war.gov release_date is present, which is a publication date, "
        "not a document era"
        if card.get("release_date")
        else "no date on any manifest field"
    )
    return {
        "card_id": card_era.card_id,
        "identifier": card_era.identifier,
        "title": card_era.title,
        "agency": card_era.agency,
        "available_dates": {
            "display_date": card.get("display_date"),
            "incident_date": card.get("incident_date"),
            "release_date": card.get("release_date"),
        },
        "reason": reason,
    }


@dataclass
class BucketResult:
    """The full outcome: per-card assignments, 2015+ negatives, triage, counts."""

    cards: list[CardEra]
    claims: list[EraNoPriorRelease]
    triage: list[dict[str, Any]]
    era_counts: dict[str, int] = field(default_factory=dict)
    agency_counts: dict[str, int] = field(default_factory=dict)


def bucket(manifest: dict[str, Any]) -> BucketResult:
    """Bucket every card by era and agency; emit 2015+ negatives + triage."""
    raw_cards = manifest.get("cards", [])
    classified = [classify_card(card) for card in raw_cards]
    claims = [_no_prior_release(ce) for ce in classified if ce.era is Era.MODERN_OPERATIONAL]
    triage = [
        _triage_entry(ce, card)
        for ce, card in zip(classified, raw_cards, strict=True)
        if ce.era is Era.UNDATED
    ]
    era_counts = {era.value: 0 for era in Era}
    era_counts.update(Counter(ce.era.value for ce in classified))
    agency_counts = dict(sorted(Counter(ce.agency for ce in classified).items()))
    return BucketResult(classified, claims, triage, era_counts, agency_counts)


def _reconciliation(era_counts: dict[str, int]) -> dict[str, Any]:
    """Compare current-manifest era counts against the §4a reference table."""
    deltas = {key: era_counts.get(key, 0) - ref for key, ref in REFERENCE_4A.items()}
    return {
        "reference_4a": REFERENCE_4A,
        "current": {key: era_counts.get(key, 0) for key in REFERENCE_4A},
        "delta": deltas,
        "matches_reference": all(delta == 0 for delta in deltas.values()),
        "note": (
            "§4a was computed against a manifest with display-date curation "
            "applied; this manifest carries a curated display_date for only a "
            "handful of cards, so undated cards that §4a dated via display_date "
            "surface here as triage. release_date (the war.gov publication date) "
            "is never used as a document era."
        ),
    }


def build_output(manifest: dict[str, Any], result: BucketResult) -> dict[str, Any]:
    """Assemble the tracked artifact: counts, reconciliation, negatives, triage."""
    return {
        "schema": _SCHEMA,
        "source_manifest": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "card_count": len(result.cards),
        "era_counts": result.era_counts,
        "agency_counts": result.agency_counts,
        "reconciliation_4a": _reconciliation(result.era_counts),
        "no_prior_release_count": len(result.claims),
        "no_prior_release": [claim.to_dict() for claim in result.claims],
        "undated_triage_count": len(result.triage),
        "undated_triage": result.triage,
        "cards": [ce.to_dict() for ce in result.cards],
    }


def main() -> int:
    """CLI: bucket ``data/manifests/latest.json`` -> the tracked artifact."""
    repo_root = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo_root / "data" / "manifests" / "latest.json").read_text())
    result = bucket(manifest)
    out_path = repo_root / OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build_output(manifest, result), indent=2) + "\n")
    labelled = ", ".join(f"{ERA_LABELS[era]}={result.era_counts[era.value]}" for era in Era)
    print(f"era bucketing: {len(result.cards)} cards -> {labelled}")
    print(f"  {len(result.claims)} no_prior_release (2015+); {len(result.triage)} undated (triage)")
    print(f"  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
