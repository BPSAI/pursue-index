"""The 2015+ no-prior-release record, built from an already-classified row."""

from __future__ import annotations

from pursue_index.era_models import CardEra, EraNoPriorRelease, era_rationale

__all__ = ["no_prior_release"]


def no_prior_release(card_era: CardEra) -> EraNoPriorRelease:
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
        rationale += f" This row names the same source file as {card_era.era_reconciled_from}, whose date it takes."
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
