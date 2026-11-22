"""The spend line shows the figure the cap enforces and the list-price estimate."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.vision import spend
from tests.unit.test_vision_cli import _img_card, _patch_seams, _write_manifest

runner = CliRunner()


def test_list_rates_sit_beside_the_ceiling_table() -> None:
    r = spend.LIST_RATES_BY_MODEL["claude-opus-4-8"]
    assert (r.input, r.output) == (5.00, 25.00)
    c = spend.RATES_BY_MODEL["claude-opus-4-8"]
    assert (c.input, c.output) == (15.00, 75.00)  # the cap's rates are untouched


def test_list_figure_prices_the_same_usage_at_list_rates() -> None:
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert spend.usage_cost_usd("claude-opus-4-8", usage) == pytest.approx(90.0)
    assert spend.list_usage_cost_usd("claude-opus-4-8", usage) == pytest.approx(30.0)


def test_the_cap_does_not_move() -> None:
    b = spend.SpendBudget(cap_usd=1.0, model="claude-opus-4-8")
    b.reserve()
    b.settle({"input_tokens": 1500, "output_tokens": 300})
    assert b.spent_usd == pytest.approx((1500 * 15 + 300 * 75) / 1e6)
    assert b.spent_list_usd == pytest.approx((1500 * 5 + 300 * 25) / 1e6)


def test_live_spend_line_format(tmp_path, monkeypatch) -> None:
    def examine(_img, **_k):
        return {"image_type": "p", "description": "d", "visible_text": "",
                "observations": [{"claim": "c"}],
                "_usage": {"input_tokens": 1_000, "output_tokens": 1_000}}

    _patch_seams(monkeypatch, examine)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("a1a1a1a1a1a1a1a1")])
    result = runner.invoke(app, ["vision", "run", "--manifest", str(manifest),
                                 "--out", str(tmp_path / "o"), "--live", "--confirm-live",
                                 "--budget-usd", "1.0"])
    assert result.exit_code == 0, result.output
    # 1000 in + 1000 out: ceiling 0.0900, list 0.0300
    assert "vision spend: $0.0900 metered at ceiling rates (≈ $0.0300 at list) of $1.00" in (
        " ".join(result.output.split()))


def test_list_figure_prices_the_metered_token_counts_not_a_ratio(monkeypatch) -> None:
    # List input/output rates whose ratio differs from the ceiling's, with an
    # input-heavy mix: scaling the ceiling total by any one ratio misprices it.
    monkeypatch.setitem(
        spend.LIST_RATES_BY_MODEL, "claude-opus-4-8", spend.ModelRates(input=2.0, output=25.0)
    )
    b = spend.SpendBudget(cap_usd=100.0, model="claude-opus-4-8")
    usages = [
        {"input_tokens": 90_000, "cache_creation_input_tokens": 10_000,
         "cache_read_input_tokens": 40_000, "output_tokens": 1_000},
        {"input_tokens": 50_000, "output_tokens": 2_000},
    ]
    for u in usages:
        b.reserve()
        b.settle(u)
    plain, write, read, out = 140_000, 10_000, 40_000, 3_000
    expected = (plain * 2 + write * 2 * 1.25 + read * 2 * 0.10 + out * 25) / 1e6
    assert b.spent_list_usd == pytest.approx(expected)
    assert abs(b.spent_usd * (25 / 75) - expected) > 0.01


def test_a_missing_usage_report_is_listed_at_worst_case_tokens() -> None:
    b = spend.SpendBudget(cap_usd=100.0, model="claude-opus-4-8")
    b.reserve()
    b.settle(None)
    worst = spend.worst_case_list_usd("claude-opus-4-8")
    assert b.spent_list_usd == pytest.approx(worst)
