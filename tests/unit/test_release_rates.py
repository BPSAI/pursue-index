"""The per-page rates table and the cost band it prices (R7C.5).

Release 7's poll estimate was a per-card OCR+embed guess ($6.98) against
$38.22 actually spent on 1,140 pages. ``release/rates.py`` prices every spend
stage (OCR, clean, clean-qc judge, embed) per page, low from observed spend and
high from each stage's worst case, and recommends a cap between them.
"""

from __future__ import annotations

import math

import pytest

from pursue_index.release import rates
from pursue_index.release.rates import (
    CAP_MARGIN,
    RATES_TABLE,
    RatesTableError,
    StageRate,
    cost_band,
)

_RELEASE_7_PAGES = 1_140
_RELEASE_7_SPENT_USD = 38.22


def test_table_prices_every_spend_stage() -> None:
    assert set(RATES_TABLE) == {"ocr", "clean", "judge", "embed"}
    assert CAP_MARGIN == 0.5


def test_observed_low_rates_are_the_release_7_figures() -> None:
    assert RATES_TABLE["ocr"].low == 0.0130
    assert RATES_TABLE["clean"].low == 0.0026
    assert RATES_TABLE["judge"].low == 0.0165
    assert RATES_TABLE["embed"].low == 0.00003


def test_band_for_111_pages_matches_the_table_per_stage() -> None:
    band = cost_band(111)
    assert band.pages == 111
    for stage, rate in RATES_TABLE.items():
        assert band.stages[stage].low == pytest.approx(111 * rate.low)
        assert band.stages[stage].high == pytest.approx(111 * rate.high)
    assert band.low == pytest.approx(111 * sum(r.low for r in RATES_TABLE.values()))
    assert band.high == pytest.approx(111 * sum(r.high for r in RATES_TABLE.values()))


def test_release_7_replay_lands_near_actual_spend_with_cap_below_worst_case() -> None:
    band = cost_band(_RELEASE_7_PAGES)
    assert abs(band.low - _RELEASE_7_SPENT_USD) <= 0.25 * _RELEASE_7_SPENT_USD
    assert band.cap == math.ceil(band.low * 1.5)
    assert band.cap < band.high
    assert band.high > 160  # the worst case the task text cites


def test_cap_is_a_whole_dollar_rounded_up() -> None:
    band = cost_band(_RELEASE_7_PAGES)
    assert band.cap == int(band.cap)
    assert band.cap >= band.low * (1 + CAP_MARGIN)


def test_table_with_no_room_for_a_cap_reports_an_error_not_a_cap() -> None:
    cramped = {"ocr": StageRate(low=0.10, high=0.15)}  # 0.10 * 1.5 == 0.15
    with pytest.raises(RatesTableError, match="cap"):
        cost_band(100, table=cramped)


def test_table_whose_low_exceeds_high_reports_an_error() -> None:
    inverted = {"ocr": StageRate(low=0.20, high=0.10)}
    with pytest.raises(RatesTableError):
        cost_band(100, table=inverted)


def test_small_tranche_cap_stays_below_the_worst_case() -> None:
    """Whole-dollar rounding would put a 1-page cap ($1) above the page's
    worst case (~$0.25); the cap falls back to cents rather than not binding."""
    band = cost_band(1)
    assert band.low * (1 + CAP_MARGIN) <= band.cap < band.high


class _StubHardCapLedger:
    """Stand-in for R7C.6's hard-cap ledger: refuses the call that would
    take cumulative spend past the cap."""

    class CapReachedError(Exception):
        pass

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0

    def charge(self, usd: float) -> None:
        if self.spent_usd + usd > self.cap_usd:
            raise self.CapReachedError(f"${self.spent_usd + usd:.2f} > cap ${self.cap_usd:.2f}")
        self.spent_usd += usd


@pytest.mark.parametrize("pages", [111, _RELEASE_7_PAGES])
def test_cap_binds_before_a_worst_case_run_finishes(pages: int) -> None:
    band = cost_band(pages)
    worst_per_page = sum(r.high for r in RATES_TABLE.values())
    ledger = _StubHardCapLedger(band.cap)
    finished = 0
    with pytest.raises(_StubHardCapLedger.CapReachedError):
        for _ in range(pages):
            ledger.charge(worst_per_page)
            finished += 1
    assert finished < pages
    assert ledger.spent_usd <= band.cap


def test_cards_without_a_page_count_are_priced_per_card_and_mark_the_band_partial() -> None:
    band = cost_band(111, fallback_card_ids=["c0ffee0000000001"])
    assert band.counted_pages == 111
    assert band.fallback_card_ids == ("c0ffee0000000001",)
    assert band.pages == 111 + rates.AVG_PAGES_PER_CARD
    assert band.partial is True
    assert cost_band(111).partial is False
