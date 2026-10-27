"""The spending seam rejects nonsense inputs; punctuation is not a word."""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.transcribe import asr_diff
from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar


def _run(tmp_path: Path, *, duration: float, rate: float, budget: runner.AsrDiffBudget, calls: list):
    def engine_b(_p: Path) -> str:
        calls.append(1)
        return "one two"

    return runner.run_row(
        card_id="c", row_key="", engine_a="a", engine_b="b", text_a="one two",
        audio_path=tmp_path / "x.wav", sidecar_path=tmp_path / sidecar.SIDECAR_FILE,
        second_engine_fn=engine_b, audio_duration_s=duration,
        rate_usd_per_minute=rate, budget=budget,
    )


@pytest.mark.parametrize(
    ("duration", "rate"),
    [(-60.0, 1.0), (60.0, -1.0), (float("nan"), 1.0), (60.0, float("inf"))],
)
def test_negative_or_non_finite_cost_inputs_are_refused_before_any_call(
    tmp_path: Path, duration: float, rate: float,
) -> None:
    calls: list = []
    budget = runner.AsrDiffBudget(cap_usd=5.0)
    with pytest.raises(ValueError, match=r"duration|rate"):
        _run(tmp_path, duration=duration, rate=rate, budget=budget, calls=calls)
    assert calls == [] and budget.spent_usd == 0.0
    assert sidecar.load_existing(tmp_path / sidecar.SIDECAR_FILE) == {}


@pytest.mark.parametrize("cap", [-1.0, float("nan"), float("inf")])
def test_a_negative_or_non_finite_budget_cap_is_refused(cap: float) -> None:
    with pytest.raises(ValueError, match="cap"):
        runner.AsrDiffBudget(cap_usd=cap)


def test_punctuation_only_transcripts_are_not_judged() -> None:
    result = asr_diff.align_transcripts("...", "!!!")
    assert result.word_count_a == 0 and result.word_count_b == 0
    assert asr_diff.classify_result(result) == "review"


def test_punctuation_tokens_do_not_count_as_words_beside_real_ones() -> None:
    result = asr_diff.align_transcripts("hello ... world", "hello world")
    assert (result.word_count_a, result.word_count_b) == (2, 2)
    assert result.agreement == 1.0
