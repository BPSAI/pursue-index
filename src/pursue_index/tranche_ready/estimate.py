"""The tranche-ready record's ``estimate`` block (``$defs/estimate``).

A projection of ``release.rates.cost_band`` -- the same pricing the poll
issue and ``ingest approve`` quote -- into the schema's shape: per-stage
per-page rates and totals, the low and worst-case totals, and the
recommended cap (``rates.recommended_cap``: ``ceil(low * (1 + CAP_MARGIN))``
while that stays below the worst case). Nothing is priced here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pursue_index.release import rates

__all__ = ["estimate_block"]

_LABELS = {rates.JUDGE_METERED: "metered", rates.JUDGE_TABLE_ESTIMATE: "table-estimate"}


def _per_page(judge: rates.JudgeRate | None) -> dict[str, rates.StageRate]:
    """The rates ``cost_band`` priced with: the table, judge low overridden."""
    table = dict(rates.RATES_TABLE)
    if judge is not None and "judge" in table:
        table["judge"] = rates.StageRate(low=judge.usd_per_page, high=table["judge"].high)
    return table


def estimate_block(
    counted_pages: int, fallback_card_ids: Sequence[str], judge: rates.JudgeRate | None,
) -> dict[str, Any]:
    """``counted_pages`` plus the per-card guess for each fallback card, priced."""
    band = rates.cost_band(counted_pages, fallback_card_ids=fallback_card_ids, judge=judge)
    per_page = _per_page(judge)
    stages = [
        {
            "stage": name,
            "low_rate_per_page": round(per_page[name].low, 6),
            "high_rate_per_page": round(per_page[name].high, 6),
            "low_usd": round(stage.low, 2),
            "high_usd": round(stage.high, 2),
        }
        for name, stage in band.stages.items()
    ]
    # Totals are the sums of the per-stage figures the record shows, so the
    # record adds up (pursue-opsec's check holds the stage sum to low_usd
    # within a cent), and the cap is the rates formula over that low.
    low = round(sum(s["low_usd"] for s in stages), 2)
    high = round(sum(s["high_usd"] for s in stages), 2)
    return {
        "basis": "per-card-fallback" if counted_pages == 0 and band.partial else "page-counted",
        "partial": band.partial,
        "judge_figure_label": _LABELS.get(band.judge_label, "table-estimate"),
        "cap_margin": rates.CAP_MARGIN,
        "low_usd": low,
        "high_usd": high,
        "recommended_cap_usd": float(rates.recommended_cap(low, high)),
        "fallback_cards": list(fallback_card_ids),
        "per_stage": stages,
    }
