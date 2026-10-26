"""``--live --budget-usd`` is a hard cap on real spend, not on a flat guess.

The vision stage meters each response's reported usage at the model's rates and
refuses to start a call whose worst case would not fit in what is left. The
flat per-call estimate survives only as the pre-call reservation, which the
response's real cost replaces.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from pursue_index.vision import client
from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.run import ESTIMATED_COST_PER_CALL_USD, run_vision
from pursue_index.vision.spend import (
    SpendBudget,
    usage_cost_usd,
    worst_case_call_usd,
)

_MODEL = client.VISION_MODEL


def _items(n: int) -> list[EligibleItem]:
    return [
        EligibleItem(card_id=f"img{i}", page=1, kind="img_card",
                     image_path=Path(f"/tmp/img{i}"), title="T", row_key="")
        for i in range(n)
    ]


def _examiner(usage: dict[str, int] | None, calls: list[int]):
    def examine(_img: object) -> dict[str, Any]:
        calls.append(1)
        out: dict[str, Any] = {"image_type": "photo", "description": "d",
                               "visible_text": "", "observations": []}
        if usage is not None:
            out["_usage"] = dict(usage)
        return out
    return examine


def _run(n: int, budget: float, usage: dict[str, int] | None, tmp: Path):
    calls: list[int] = []
    report = run_vision(
        _items(n), tmp, examine_fn=_examiner(usage, calls),
        load_image_fn=lambda _i: object(), budget_usd=budget,
    )
    return report, len(calls)


def test_worst_case_call_dwarfs_the_flat_estimate() -> None:
    assert worst_case_call_usd(_MODEL) > 5 * ESTIMATED_COST_PER_CALL_USD


def test_usage_is_priced_at_the_model_rates_including_cache_tokens() -> None:
    plain = usage_cost_usd(_MODEL, {"input_tokens": 1_000_000, "output_tokens": 0})
    out = usage_cost_usd(_MODEL, {"input_tokens": 0, "output_tokens": 1_000_000})
    write = usage_cost_usd(
        _MODEL, {"input_tokens": 0, "output_tokens": 0,
                 "cache_creation_input_tokens": 1_000_000})
    assert plain and out and write
    assert write == pytest.approx(1.25 * plain)
    assert usage_cost_usd(_MODEL, None) is None


def test_cheap_responses_let_the_budget_cover_more_than_a_worst_case_each(
    tmp_path: Path,
) -> None:
    usage = {"input_tokens": 1_000, "output_tokens": 500}
    report, calls = _run(3, 0.45, usage, tmp_path)
    assert calls == 3
    assert report.ok
    assert report.spent_usd == pytest.approx(3 * usage_cost_usd(_MODEL, usage))


def test_expensive_responses_stop_the_run_before_the_cap_is_passed(
    tmp_path: Path,
) -> None:
    usage = {"input_tokens": 6_000, "output_tokens": 2_048}
    cap = 0.5
    report, calls = _run(10, cap, usage, tmp_path)
    assert calls == 2  # a third call's worst case no longer fits
    assert report.spent_usd <= cap
    assert not report.ok


def test_a_response_without_usage_is_charged_its_worst_case(tmp_path: Path) -> None:
    report, calls = _run(10, 0.5, None, tmp_path)
    assert calls == 2
    assert report.spent_usd == pytest.approx(2 * worst_case_call_usd(_MODEL))


def test_usage_never_reaches_the_sidecar(tmp_path: Path) -> None:
    _run(1, 1.0, {"input_tokens": 10, "output_tokens": 10}, tmp_path)
    assert "_usage" not in json.loads((tmp_path / "img0.json").read_text())["pages"][0]


def test_a_failed_call_keeps_its_reservation_charged() -> None:
    budget = SpendBudget(cap_usd=1.0, model=_MODEL)
    assert budget.can_start()
    budget.reserve()
    assert budget.spent_usd == pytest.approx(ESTIMATED_COST_PER_CALL_USD)


def test_the_client_reports_the_response_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = SimpleNamespace(input_tokens=11, output_tokens=7,
                            cache_creation_input_tokens=5, cache_read_input_tokens=3)
    reply = SimpleNamespace(
        content=[SimpleNamespace(text='{"description": "x"}')], usage=usage)
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **_k: reply))
    monkeypatch.setattr(client, "_get_anthropic_client", lambda: fake)
    result = client.examine_image(Image.new("RGB", (8, 8)))
    assert result["_usage"] == {
        "input_tokens": 11, "output_tokens": 7,
        "cache_creation_input_tokens": 5, "cache_read_input_tokens": 3,
    }


def test_vision_worst_case_shares_rates_token_assumptions() -> None:
    from pursue_index.release import rates
    from pursue_index.vision import spend

    assert spend._WORST_CASE_INPUT_TOKENS == rates.WORST_CASE_IMAGE_INPUT_TOKENS
    assert spend._CACHE_WRITE_MULTIPLE == rates.CACHE_WRITE_MULTIPLE


def test_spend_worst_case_output_tokens_match_the_request_max_tokens() -> None:
    from pursue_index.vision import client, spend

    request = client._build_request("aGk=", "claude-opus-4-8")
    assert request["max_tokens"] == spend._MAX_OUTPUT_TOKENS


def test_a_response_with_no_usage_object_reports_no_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = SimpleNamespace(content=[SimpleNamespace(text='{"description": "x"}')])
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **_k: reply))
    monkeypatch.setattr(client, "_get_anthropic_client", lambda: fake)
    result = client.examine_image(Image.new("RGB", (8, 8)))
    assert result.get("_usage") is None


def test_an_all_zero_usage_mapping_is_unavailable_not_free() -> None:
    zeros = dict.fromkeys(
        ("input_tokens", "output_tokens",
         "cache_creation_input_tokens", "cache_read_input_tokens"), 0)
    assert usage_cost_usd(_MODEL, zeros) is None
