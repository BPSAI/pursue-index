"""Per-page spend rates for a tranche — the one place per-page costs live.

Every surface that quotes a tranche's cost (the poll issue, ``pursue ingest
run``, the approval prompt and its record) prices pages from this table, so
they cannot disagree. Release 7's poll issue quoted $6.98 from a per-card
OCR+embed guess; the release spent $38.22 on 1,140 pages. Pricing every stage
per page closes that gap.

Two rates per stage:

* ``low`` — observed per-page spend (Release 7).
* ``high`` — the stage's worst case: every request bills its full
  ``max_tokens`` of output and an input sized from the largest thing the stage
  can be handed, with uncached input at the cache-write premium. The token and
  price assumptions are written out below rather than imported, so this module
  alone defines what a page costs.

The recommended cap is ``low`` plus ``CAP_MARGIN``, rounded up, and must sit
below ``high``: a cap at or above the worst case could never bind.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StageRate:
    """Low (observed) and high (worst-case) USD per page for one stage."""

    low: float
    high: float


class RatesTableError(ValueError):
    """The rates leave no room for a cap: ``low * (1 + CAP_MARGIN) >= high``."""


CAP_MARGIN = 0.5
# Pages assumed for a card whose page count is unknown (fetch failed, or not
# yet downloaded). A guess, which is why a band using it is marked partial.
AVG_PAGES_PER_CARD = 20

_M = 1_000_000

# --- worst-case assumptions per stage (tokens per page, USD per M tokens) ---
# OCR: Sonnet vision, one page image per call (ocr/llm.py). The image is
# downscaled to a 1568px long edge, which Anthropic bills at <= ~1,600 tokens;
# the system prompt is under 1,000. All input at the cache-write rate
# (1.25 x $3), output at its max_tokens=8192 ceiling.
WORST_CASE_IMAGE_INPUT_TOKENS = 1_600 + 1_000 + 20  # image + system prompt + slack
CACHE_WRITE_MULTIPLE = 1.25  # Anthropic cache-write premium over the input rate
_OCR_IN_TOKENS = WORST_CASE_IMAGE_INPUT_TOKENS
_OCR_OUT_TOKENS = 8_192
_SONNET_CACHE_WRITE, _SONNET_OUT = 1.25 * 3.00, 15.00
# clean: Haiku over one OCR page (clean/client.py). The page is at most OCR's
# 8,192-token output; the system prompt is under 1,000. Output at
# max_tokens=4096.
_CLEAN_IN_TOKENS = 8_192 + 1_000 + 20
_CLEAN_OUT_TOKENS = 4_096
_HAIKU_CACHE_WRITE, _HAIKU_OUT = 1.25 * 0.80, 4.00
# judge: Sonnet grades the raw page (<= 8,192) against its cleaned text
# (<= 4,096) under a system prompt under 2,500 (clean/qc/). Output at
# max_tokens=2048.
_JUDGE_IN_TOKENS = 8_192 + 4_096 + 2_500 + 100
_JUDGE_OUT_TOKENS = 2_048
# embed: voyage-3 at $0.06/M over one page of text, bounded by the raw OCR
# ceiling in case a page is embedded uncleaned.
_EMBED_TOKENS = 8_192
_VOYAGE = 0.06


def _usd(in_tokens: int, in_rate: float, out_tokens: int = 0, out_rate: float = 0.0) -> float:
    return in_tokens * in_rate / _M + out_tokens * out_rate / _M


RATES_TABLE: dict[str, StageRate] = {
    "ocr": StageRate(
        low=0.0130,
        high=_usd(_OCR_IN_TOKENS, _SONNET_CACHE_WRITE, _OCR_OUT_TOKENS, _SONNET_OUT),
    ),
    "clean": StageRate(
        low=0.0026,
        high=_usd(_CLEAN_IN_TOKENS, _HAIKU_CACHE_WRITE, _CLEAN_OUT_TOKENS, _HAIKU_OUT),
    ),
    "judge": StageRate(
        low=0.0165,
        high=_usd(_JUDGE_IN_TOKENS, _SONNET_CACHE_WRITE, _JUDGE_OUT_TOKENS, _SONNET_OUT),
    ),
    "embed": StageRate(low=0.00003, high=_usd(_EMBED_TOKENS, _VOYAGE)),
}


JUDGE_METERED = "metered"
JUDGE_TABLE_ESTIMATE = "table estimate"


@dataclass(frozen=True)
class JudgeRate:
    """The judge's low per-page rate and where it came from."""

    usd_per_page: float
    label: str


def _table_judge() -> JudgeRate:
    judge = RATES_TABLE.get("judge")
    return JudgeRate(usd_per_page=judge.low if judge else 0.0, label=JUDGE_TABLE_ESTIMATE)


def read_judge_rate(bundle_path: Path) -> JudgeRate:
    """The judge's per-page rate from the committed clean-qc bundle.

    ``metered_judge_spend_usd / metered_judge_calls`` (from the bundle's
    ``stats`` block, or its top level) when both are numbers and the call
    count is non-zero, labeled ``metered``. Anything else -- a missing or
    unreadable bundle, a bundle that predates the metered fields, zero calls --
    yields the table's judge figure, labeled ``table estimate``.
    """
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _table_judge()
    if not isinstance(data, dict):
        return _table_judge()
    stats = data.get("stats")
    for block in (stats if isinstance(stats, dict) else {}, data):
        spend = _number(block.get("metered_judge_spend_usd"))
        calls = _number(block.get("metered_judge_calls"))
        if spend is not None and calls:
            rate = spend / calls
            if _plausible_judge_rate(rate):
                return JudgeRate(usd_per_page=rate, label=JUDGE_METERED)
    return _table_judge()


def _plausible_judge_rate(rate: float) -> bool:
    """A metered rate outside [0, the table's judge ceiling] is bad data, not a price."""
    judge = RATES_TABLE.get("judge")
    return 0 <= rate and (judge is None or rate <= judge.high)


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


@dataclass(frozen=True)
class CostBand:
    """A tranche's priced band: per-stage low/high, totals, recommended cap.

    ``pages`` is what was priced: the ``counted_pages`` plus
    ``AVG_PAGES_PER_CARD`` for each card in ``fallback_card_ids`` (cards whose
    page count could not be obtained). Any fallback makes the band ``partial``.
    """

    pages: int
    stages: dict[str, StageRate]
    low: float
    high: float
    cap: float
    judge_label: str = JUDGE_TABLE_ESTIMATE
    counted_pages: int = 0
    fallback_card_ids: tuple[str, ...] = ()

    @property
    def partial(self) -> bool:
        return bool(self.fallback_card_ids)


def check_cap_room(table: Mapping[str, StageRate]) -> None:
    """Raise :class:`RatesTableError` unless a cap fits between low and high.

    Checked per page so the verdict does not depend on the tranche size.
    """
    low = sum(r.low for r in table.values())
    high = sum(r.high for r in table.values())
    if low * (1 + CAP_MARGIN) >= high:
        raise RatesTableError(
            f"no room for a cap: low ${low:.5f}/page x {1 + CAP_MARGIN:g} reaches "
            f"the worst case ${high:.5f}/page; fix the rates table"
        )


def recommended_cap(low: float, high: float) -> float:
    """``low * (1 + CAP_MARGIN)`` rounded up to a whole dollar, below ``high``.

    A tranche small enough that the whole dollar would reach the worst case
    gets the next cent instead, so the cap still binds.
    """
    margin = low * (1 + CAP_MARGIN)
    for step in (1.0, 0.01):
        cap = round(math.ceil(round(margin / step, 9)) * step, 2)
        if cap < high:
            return cap
    return margin


def cost_band(
    pages: int,
    *,
    fallback_card_ids: Sequence[str] = (),
    judge: JudgeRate | None = None,
    table: Mapping[str, StageRate] | None = None,
) -> CostBand:
    """Price ``pages`` counted pages, plus a per-card guess for each of
    ``fallback_card_ids``, across every stage of the rates table.

    ``judge`` (from :func:`read_judge_rate`) replaces the table's low judge
    rate and carries its label onto the band. Raises :class:`RatesTableError`
    when the table leaves no room for a cap.
    """
    table = dict(RATES_TABLE if table is None else table)
    if judge is not None and "judge" in table:
        table["judge"] = StageRate(low=judge.usd_per_page, high=table["judge"].high)
    judge_label = judge.label if judge is not None else JUDGE_TABLE_ESTIMATE
    check_cap_room(table)
    fallback = tuple(fallback_card_ids)
    priced = pages + len(fallback) * AVG_PAGES_PER_CARD
    stages = {
        name: StageRate(low=priced * r.low, high=priced * r.high) for name, r in table.items()
    }
    low = sum(s.low for s in stages.values())
    high = sum(s.high for s in stages.values())
    return CostBand(
        pages=priced, stages=stages, low=low, high=high, cap=recommended_cap(low, high),
        judge_label=judge_label, counted_pages=pages, fallback_card_ids=fallback,
    )
