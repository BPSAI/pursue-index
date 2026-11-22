"""Re-examining one card's pages for ``--redescribe`` (split from ``redescribe``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pursue_index import get_logger
from pursue_index.vision.eligibility import CoverageKey, EligibleItem
from pursue_index.vision.run import _examine_one
from pursue_index.vision.sidecar import page_has_content
from pursue_index.vision.spend import SpendBudget

log = get_logger("pursue_index.vision.redescribe")


def examine_card(
    card_items: list[EligibleItem],
    examine_fn: Callable[[Any], dict[str, Any]],
    load_image_fn: Callable[[EligibleItem], Any],
    budget: SpendBudget | None,
    failures: list[tuple[CoverageKey, str]],
    empty: list[CoverageKey],
) -> tuple[list[dict[str, Any]] | None, bool]:
    """Re-examine every page of one card; ``None`` pages when it is incomplete.

    The second value is True when the budget stopped the run.
    """
    pages: list[dict[str, Any]] = []
    complete = True
    for item in card_items:
        if budget is not None:
            if not budget.can_start():
                return None, True
            budget.reserve()
        try:
            result = _examine_one(item, examine_fn, load_image_fn, budget)
        except Exception as exc:  # one page's trouble is its own
            failures.append((item.coverage_key, f"{type(exc).__name__}: {exc}"))
            log.warning("vision.redescribe.item_failed", card_id=item.card_id,
                        page=item.page, error=str(exc))
            complete = False
            continue
        result["page"] = item.page
        result["row_key"] = item.row_key
        if not page_has_content(result):
            empty.append(item.coverage_key)
            complete = False
            continue
        pages.append(result)
    return (pages if complete else None), False
