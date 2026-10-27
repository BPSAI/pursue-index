"""Per-row ASR-diff orchestration (``pursue_index.transcribe.asr_diff_runner``).

``second_engine_fn`` is injected so these tests never hit a live ASR
vendor -- two fakes stand in for "two ASR engines" throughout. Mirrors
``clean.qc.runner``'s shape: idempotency check, budget gate, write, report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar


def _fake_engine_b(text: str) -> runner.SecondEngineFn:
    def fn(path: Path) -> str:
        return text
    return fn


def test_estimate_cost_usd_is_duration_times_rate() -> None:
    assert runner.estimate_cost_usd(audio_duration_s=120.0, rate_usd_per_minute=0.03) == pytest.approx(0.06)


def test_estimate_cost_usd_is_zero_for_zero_duration() -> None:
    assert runner.estimate_cost_usd(audio_duration_s=0.0, rate_usd_per_minute=0.03) == 0.0


def test_run_row_writes_a_judged_sidecar_when_engines_agree(tmp_path: Path) -> None:
    text_a = "the pilot reported a bright light over the ridge"
    sidecar_path = tmp_path / "card-1" / sidecar.SIDECAR_FILE
    report = runner.run_row(
        card_id="card-1", row_key="", engine_a="assemblyai", engine_b="fake-b",
        text_a=text_a, audio_path=tmp_path / "card-1.wav", sidecar_path=sidecar_path,
        second_engine_fn=_fake_engine_b(text_a), audio_duration_s=60.0,
        rate_usd_per_minute=0.03, budget=runner.AsrDiffBudget(10.0),
    )
    assert report.status == "judged"
    assert report.agreement == 1.0
    assert report.cost_usd == pytest.approx(0.03)
    loaded = sidecar.load_existing(sidecar_path)
    assert loaded[""]["status"] == "judged"


def test_run_row_writes_a_review_sidecar_when_engines_disagree_a_lot(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "card-2" / sidecar.SIDECAR_FILE
    report = runner.run_row(
        card_id="card-2", row_key="", engine_a="assemblyai", engine_b="fake-b",
        text_a="alpha beta gamma", audio_path=tmp_path / "card-2.wav",
        sidecar_path=sidecar_path, second_engine_fn=_fake_engine_b("delta epsilon zeta"),
        audio_duration_s=60.0, rate_usd_per_minute=0.03, budget=runner.AsrDiffBudget(10.0),
    )
    assert report.status == "review"
    assert len(report.disagreeing_spans) == 1


def test_run_row_is_idempotent_on_the_same_engine_pair(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "card-3" / sidecar.SIDECAR_FILE
    calls: list[Path] = []

    def counting_engine_b(path: Path) -> str:
        calls.append(path)
        return "alpha beta gamma"

    kwargs = dict(
        card_id="card-3", row_key="", engine_a="assemblyai", engine_b="fake-b",
        text_a="alpha beta gamma", audio_path=tmp_path / "card-3.wav",
        sidecar_path=sidecar_path, second_engine_fn=counting_engine_b,
        audio_duration_s=60.0, rate_usd_per_minute=0.03, budget=runner.AsrDiffBudget(10.0),
    )
    first = runner.run_row(**kwargs)
    second = runner.run_row(**kwargs)
    assert len(calls) == 1
    assert second.cost_usd == 0.0
    assert second.status == first.status == "judged"


def test_run_row_refuses_to_spend_over_budget(tmp_path: Path) -> None:
    sidecar_path = tmp_path / "card-4" / sidecar.SIDECAR_FILE
    with pytest.raises(runner.AsrDiffBudgetExceededError):
        runner.run_row(
            card_id="card-4", row_key="", engine_a="assemblyai", engine_b="fake-b",
            text_a="alpha beta gamma", audio_path=tmp_path / "card-4.wav",
            sidecar_path=sidecar_path, second_engine_fn=_fake_engine_b("alpha beta gamma"),
            audio_duration_s=6000.0, rate_usd_per_minute=0.03, budget=runner.AsrDiffBudget(0.01),
        )
    assert sidecar.load_existing(sidecar_path) == {}
