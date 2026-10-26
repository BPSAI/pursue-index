"""Operator-facing rendering of a tranche's per-page cost band.

One renderer for every surface that quotes a tranche's cost -- the poll
issue's tranche-ready block, ``pursue ingest run`` and the approval prompt --
so the judge label, the partial marker and the error-instead-of-a-cap rule
read the same everywhere. Prices come from :mod:`pursue_index.release.rates`;
nothing here computes a per-page figure.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pursue_index.release import rates

_STAGE_NAMES = {"ocr": "OCR", "clean": "clean", "judge": "judge", "embed": "embed"}
_FALLBACK_PREVIEW_CAP = 15


def _band_or_error(
    pages: int, fallback_card_ids: Sequence[str], judge: rates.JudgeRate | None
) -> rates.CostBand | str:
    try:
        return rates.cost_band(pages, fallback_card_ids=fallback_card_ids, judge=judge)
    except rates.RatesTableError as exc:
        return str(exc)


def _stage_line(band: rates.CostBand) -> str:
    parts = []
    for name, cost in band.stages.items():
        label = f" ({band.judge_label})" if name == "judge" else ""
        parts.append(
            f"{_STAGE_NAMES.get(name, name)} ${cost.low:,.2f}-${cost.high:,.2f}{label}"
        )
    return "* per stage (low-worst case): " + " · ".join(parts)


def _fallback_lines(band: rates.CostBand) -> list[str]:
    ids = [cid for cid in band.fallback_card_ids if cid]
    n = len(band.fallback_card_ids)
    line = (
        f"* **partial:** {n} card(s) had no page count and were priced at "
        f"{rates.AVG_PAGES_PER_CARD} pages each (per-card fallback)"
    )
    shown = ", ".join(f"`{cid}`" for cid in ids[:_FALLBACK_PREVIEW_CAP])
    if shown:
        more = len(ids) - _FALLBACK_PREVIEW_CAP
        line += ": " + shown + (f" … and {more} more" if more > 0 else "")
    return [line]


def _usd_cap(cap: float) -> str:
    return f"${cap:,.0f}" if cap == int(cap) else f"${cap:,.2f}"


def estimate_lines(
    *, pages: int, fallback_card_ids: Sequence[str], judge: rates.JudgeRate | None
) -> list[str]:
    """Markdown lines for the band, cap, judge label and any fallback cards."""
    band = _band_or_error(pages, fallback_card_ids, judge)
    if isinstance(band, str):
        return [f"**Est. cost:** error — {band} (no cap recommended)"]
    title = "Est. cost (partial)" if band.partial else "Est. cost"
    lines = [
        f"**{title}:** ${band.low:,.2f} low to ${band.high:,.2f} worst case over "
        f"{band.pages:,} pages · recommended cap {_usd_cap(band.cap)}",
        _stage_line(band),
        f"* judge rate: {band.judge_label}",
    ]
    if band.partial:
        lines += _fallback_lines(band)
    return lines



def estimate_record(
    *, pages: int, fallback_card_ids: Sequence[str], judge: rates.JudgeRate | None
) -> dict[str, Any]:
    """The same estimate as a JSON-serializable row for an audit record."""
    band = _band_or_error(pages, fallback_card_ids, judge)
    label = judge.label if judge is not None else rates.JUDGE_TABLE_ESTIMATE
    if isinstance(band, str):
        return {"error": band, "judge_label": label}
    return {
        "pages": band.pages,
        "counted_pages": band.counted_pages,
        "low_usd": round(band.low, 2),
        "high_usd": round(band.high, 2),
        "cap_usd": band.cap,
        "judge_label": band.judge_label,
        "partial": band.partial,
        "fallback_card_ids": list(band.fallback_card_ids),
    }
