"""The rendered per-page estimate every cost surface shares (R7C.5).

``estimate_lines`` turns counted pages, the cards that fell back to the
per-card guess, and the judge rate into operator-facing lines: the low/high
band, the recommended cap, the judge figure with its label, and -- when any
card fell back -- which ones, with the figure marked partial. A rates table
with no room for a cap renders an error in place of a cap.
"""

from __future__ import annotations

from pursue_index.release import rates
from pursue_index.release.estimate_text import estimate_lines
from pursue_index.release.rates import (
    JUDGE_METERED,
    JUDGE_TABLE_ESTIMATE,
    JudgeRate,
    StageRate,
    cost_band,
)


def _text(**kw) -> str:
    return "\n".join(estimate_lines(**kw))


def test_full_count_shows_band_cap_and_table_label() -> None:
    band = cost_band(1_140)
    text = _text(pages=1_140, fallback_card_ids=[], judge=None)
    assert f"${band.low:,.2f}" in text
    assert f"${band.high:,.2f}" in text
    assert f"${band.cap:,.0f}" in text
    assert "1,140 pages" in text
    assert JUDGE_TABLE_ESTIMATE in text
    assert JUDGE_METERED not in text
    assert "partial" not in text.lower()


def test_metered_judge_is_labeled_metered() -> None:
    text = _text(pages=10, fallback_card_ids=[], judge=JudgeRate(0.02, JUDGE_METERED))
    assert "(metered)" in text
    assert JUDGE_TABLE_ESTIMATE not in text


def test_fallback_cards_are_named_and_the_figure_is_partial() -> None:
    text = _text(pages=111, fallback_card_ids=["deadbeef00000001"], judge=None)
    assert "partial" in text.lower()
    assert "deadbeef00000001" in text
    assert f"{rates.AVG_PAGES_PER_CARD} pages" in text


def test_rates_table_without_cap_room_renders_an_error_not_a_cap(monkeypatch) -> None:
    monkeypatch.setattr(rates, "RATES_TABLE", {"ocr": StageRate(low=0.1, high=0.1)})
    text = _text(pages=100, fallback_card_ids=[], judge=None)
    assert "error" in text.lower()
    assert "cap $" not in text.lower()


def test_a_cents_cap_on_a_tiny_tranche_is_shown_in_cents() -> None:
    band = cost_band(1)
    text = _text(pages=1, fallback_card_ids=[], judge=None)
    assert f"recommended cap ${band.cap:.2f}" in text
