"""Security hardening for the second-engine ASR diff (budget, status, ids)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.card_id import InvalidCardIdError
from pursue_index.cli.commands import app
from pursue_index.transcribe import asr_diff
from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_asr_diff_bundle  # type: ignore[import-not-found] # noqa: E402

CARD = "a" * 16


def _run(tmp_path: Path, name: str, budget: runner.AsrDiffBudget, minutes: float = 1.0):
    return runner.run_row(
        card_id=name, row_key="", engine_a="a", engine_b="b",
        text_a="one two three", audio_path=tmp_path / "x.wav",
        sidecar_path=tmp_path / name / sidecar.SIDECAR_FILE,
        second_engine_fn=lambda p: "one two three",
        audio_duration_s=minutes * 60, rate_usd_per_minute=1.0, budget=budget,
    )


def test_shared_budget_accumulates_across_rows_and_stops_at_cap(tmp_path: Path) -> None:
    budget = runner.AsrDiffBudget(cap_usd=2.5)
    _run(tmp_path, "r1", budget)
    _run(tmp_path, "r2", budget)
    assert budget.spent_usd == pytest.approx(2.0)
    with pytest.raises(runner.AsrDiffBudgetExceededError) as exc:
        _run(tmp_path, "r3", budget)
    assert exc.value.partial_cost_usd == pytest.approx(2.0)
    assert not (tmp_path / "r3" / sidecar.SIDECAR_FILE).exists()


def test_run_rows_bulk_loop_stops_at_the_cap(tmp_path: Path) -> None:
    budget = runner.AsrDiffBudget(cap_usd=2.5)
    calls = [lambda n=n: _run(tmp_path, n, budget) for n in ("b1", "b2", "b3", "b4")]
    reports, stopped = runner.run_rows(calls)
    assert len(reports) == 2 and stopped is not None


def test_zero_word_transcripts_classify_as_review() -> None:
    both = asr_diff.align_transcripts("", "")
    assert asr_diff.classify_result(both) == "review"
    one = asr_diff.align_transcripts("hello there", "")
    assert asr_diff.classify_result(one) == "review"
    ok = asr_diff.align_transcripts("hello there", "hello there")
    assert asr_diff.classify_result(ok) == "judged"


def test_runner_marks_two_empty_transcripts_review(tmp_path: Path) -> None:
    report = runner.run_row(
        card_id=CARD, row_key="", engine_a="a", engine_b="b", text_a="",
        audio_path=tmp_path / "x.wav", sidecar_path=tmp_path / CARD / sidecar.SIDECAR_FILE,
        second_engine_fn=lambda p: "", audio_duration_s=60.0,
        rate_usd_per_minute=0.01, budget=runner.AsrDiffBudget(cap_usd=1.0),
    )
    assert report.status == "review"


def _bundle(status: object, agreement: object = 0.5, threshold: object = 0.9) -> dict:
    return {"cards": [{
        "card_id": CARD, "status": status, "agreement": agreement,
        "threshold": threshold, "min_words": 5,
    }]}


def test_tampered_judged_status_is_rederived_from_agreement() -> None:
    assert build_asr_diff_bundle.as_status_map(_bundle("judged", 0.5)) == {CARD: "review"}


def test_genuine_judged_status_survives_rederivation() -> None:
    assert build_asr_diff_bundle.as_status_map(_bundle("judged", 0.97)) == {CARD: "judged"}


def test_unknown_status_and_missing_evidence_become_review(caplog) -> None:
    assert build_asr_diff_bundle.as_status_map(_bundle("verified", 0.99)) == {CARD: "review"}
    no_evidence = {"cards": [{"card_id": CARD, "status": "judged"}]}
    assert build_asr_diff_bundle.as_status_map(no_evidence) == {CARD: "review"}


def test_bundle_build_carries_agreement_evidence(tmp_path: Path) -> None:
    d = tmp_path / CARD
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"status": "ok", "rows": [{"row_key": ""}], "finished_at": "v1"}))
    (d / sidecar.SIDECAR_FILE).write_text(json.dumps({
        "row_key": "", "status": "judged", "agreement": 0.95, "threshold": 0.9,
        "word_count_a": 10, "word_count_b": 10, "transcript_version": "v1",
    }) + "\n")
    card = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=[CARD])["cards"][0]
    assert card["agreement"] == 0.95 and card["threshold"] == 0.9 and card["status"] == "judged"


def test_bundle_build_rejects_traversal_card_id(tmp_path: Path) -> None:
    with pytest.raises(InvalidCardIdError):
        build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=["../../etc"])


def test_cli_rejects_traversal_card_id(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text("{}")
    res = CliRunner().invoke(app, [
        "transcribe", "asr-diff", "run", "--manifest", str(manifest),
        "--cards", "../../etc", "--engine-b", "x", "--rate-usd-per-minute", "0.1",
    ])
    assert res.exit_code != 0
    assert "invalid card_id" in res.output
