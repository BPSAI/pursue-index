"""``pursue_index.tranche_ready.estimate`` -- the record's ``estimate`` block.

Priced by ``release/rates.py`` (``cost_band``, ``CAP_MARGIN``,
``read_judge_rate``) and nothing else, so the record, the poll issue and
``ingest approve`` cannot quote different figures for the same pages.
Release 7's 1,140 pages with the judge at its metered 0.0165/page give the
pinned example's low $36.62 and cap $55 -- ``ceil(low * 1.5)``, not $56.
"""

from __future__ import annotations

import math

from pursue_index.release import rates
from pursue_index.tranche_ready.estimate import estimate_block

_METERED = rates.JudgeRate(usd_per_page=0.0165, label=rates.JUDGE_METERED)


def test_release_7_pages_reproduce_the_example_low_and_cap() -> None:
    est = estimate_block(1140, [], _METERED)
    assert (est["low_usd"], est["recommended_cap_usd"]) == (36.62, 55.0)
    assert est["recommended_cap_usd"] == math.ceil(est["low_usd"] * (1 + est["cap_margin"]))
    assert (est["basis"], est["partial"], est["judge_figure_label"]) == (
        "page-counted", False, "metered")
    assert est["cap_margin"] == rates.CAP_MARGIN
    assert [s["stage"] for s in est["per_stage"]] == ["ocr", "clean", "judge", "embed"]
    assert [s["low_usd"] for s in est["per_stage"]] == [14.82, 2.96, 18.81, 0.03]
    assert est["per_stage"][2]["low_rate_per_page"] == 0.0165


def test_totals_are_the_sums_of_the_stage_figures_the_record_shows() -> None:
    """pursue-opsec's check holds sum(per_stage.low_usd) to low_usd within a
    cent; ``round(band.low, 2)`` (36.63) would miss the example's 36.62."""
    est = estimate_block(1140, [], _METERED)
    assert est["low_usd"] == round(sum(s["low_usd"] for s in est["per_stage"]), 2)
    assert est["high_usd"] == round(sum(s["high_usd"] for s in est["per_stage"]), 2)


def test_the_worst_case_is_the_rates_table_ceiling() -> None:
    est = estimate_block(1140, [], _METERED)
    band = rates.cost_band(1140, judge=_METERED)
    assert abs(est["high_usd"] - band.high) < 0.05
    assert est["recommended_cap_usd"] < est["high_usd"]
    ocr = est["per_stage"][0]
    assert ocr["high_rate_per_page"] == round(rates.RATES_TABLE["ocr"].high, 6)


def test_table_judge_label_uses_the_schema_spelling() -> None:
    est = estimate_block(10, [], rates.JudgeRate(0.0165, rates.JUDGE_TABLE_ESTIMATE))
    assert est["judge_figure_label"] == "table-estimate"
    assert estimate_block(10, [], None)["judge_figure_label"] == "table-estimate"


def test_fallback_cards_make_it_partial_and_all_fallback_changes_the_basis() -> None:
    est = estimate_block(100, ["a" * 16], _METERED)
    assert (est["partial"], est["basis"], est["fallback_cards"]) == (
        True, "page-counted", ["a" * 16])
    priced = 100 + rates.AVG_PAGES_PER_CARD
    assert abs(est["low_usd"] - rates.cost_band(priced, judge=_METERED).low) < 0.05
    assert estimate_block(0, ["a" * 16], _METERED)["basis"] == "per-card-fallback"
