"""Trust boundaries of the ASR-diff bundle: threshold floor, row coverage,
transcript-bound idempotency, and a status distinct from page-judging."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pursue_index.clean.qc.coverage import STATUSES, build_coverage
from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_asr_diff_bundle  # type: ignore[import-not-found] # noqa: E402
import build_qc_coverage  # type: ignore[import-not-found] # noqa: E402

CARD = "d1" * 8


def _row(row_key: str, agreement: float, threshold: float = 0.9) -> dict:
    return {
        "row_key": row_key, "engine_a": "a", "engine_b": "b", "status": "judged",
        "agreement": agreement, "threshold": threshold,
        "word_count_a": 20, "word_count_b": 20,
    }


def _card(tmp_path: Path, meta_rows: list[str] | None, rows: list[dict]) -> None:
    d = tmp_path / CARD
    d.mkdir(parents=True, exist_ok=True)
    if meta_rows is not None:
        (d / "meta.json").write_text(json.dumps({
            "status": "ok", "rows": [{"row_key": k} for k in meta_rows],
            "finished_at": "v1",
        }))
    stamped = [{**r, "transcript_version": "v1"} for r in rows]
    (d / sidecar.SIDECAR_FILE).write_text("\n".join(json.dumps(r) for r in stamped) + "\n")


def _status(tmp_path: Path) -> list[tuple[str, str]]:
    bundle = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=[CARD])
    return [(c["card_id"], c["status"]) for c in bundle["cards"]]


def test_a_lowered_published_threshold_cannot_mint_judged(tmp_path: Path) -> None:
    bundle = {"cards": [{"card_id": CARD, "status": "judged", "agreement": 0.5,
                         "threshold": 0.0, "min_words": 20}]}
    assert build_asr_diff_bundle.as_status_map(bundle) == {CARD: "review"}
    _card(tmp_path, [""], [_row("", 0.5, threshold=0.0)])
    assert _status(tmp_path) == [(CARD, "review")]


def test_a_card_missing_a_row_comparison_does_not_graduate(tmp_path: Path) -> None:
    _card(tmp_path, ["a", "b"], [_row("a", 0.99)])
    assert _status(tmp_path) == []


def test_a_flagged_row_still_surfaces_when_another_row_is_uncompared(tmp_path: Path) -> None:
    _card(tmp_path, ["a", "b"], [_row("a", 0.4)])
    assert _status(tmp_path) == [(CARD, "review")]


def test_a_stale_sidecar_row_for_a_vanished_row_key_is_ignored(tmp_path: Path) -> None:
    _card(tmp_path, ["a"], [_row("a", 0.99), _row("gone", 0.1)])
    assert _status(tmp_path) == [(CARD, "judged")]


def test_a_card_without_readable_meta_is_omitted(tmp_path: Path) -> None:
    _card(tmp_path, None, [_row("", 0.99)])
    assert _status(tmp_path) == []


def _run(tmp_path: Path, text_a: str, calls: list[int]):
    def engine_b(_p: Path) -> str:
        calls.append(1)
        return text_a

    return runner.run_row(
        card_id=CARD, row_key="", engine_a="a", engine_b="b", text_a=text_a,
        audio_path=tmp_path / "x.wav", sidecar_path=tmp_path / sidecar.SIDECAR_FILE,
        second_engine_fn=engine_b, audio_duration_s=60.0, rate_usd_per_minute=0.01,
        budget=runner.AsrDiffBudget(10.0),
    )


def test_a_changed_engine_a_transcript_is_compared_again(tmp_path: Path) -> None:
    calls: list[int] = []
    _run(tmp_path, "one two three", calls)
    _run(tmp_path, "one two three", calls)
    assert len(calls) == 1
    _run(tmp_path, "one two three four", calls)
    assert len(calls) == 2


def test_a_legacy_row_without_a_transcript_hash_is_not_trusted() -> None:
    row = {"engine_a": "a", "engine_b": "b"}
    assert sidecar.should_skip(row, engine_a="a", engine_b="b")
    assert not sidecar.should_skip(row, engine_a="a", engine_b="b", text_a_sha256="ab")


def _coverage(asr: dict[str, str]) -> dict:
    manifest = {"csv_sha256": "c" * 64, "fetched_at": "2026-09-01T00:00:00+00:00",
                "cards": [{"card_id": "aud", "asset_type": "AUD"}]}
    bundle = {"bundle_schema_version": 1, "generated_at": "2026-09-02T00:00:00+00:00",
              "runner_version": "0.2.0", "judge_model": "j", "cards": []}
    pages = [{"card_id": "aud", "page": 1, "text": "transcript"}]
    return build_coverage(manifest, bundle, pages, {"card_ids": []}, {}, None, asr)


def test_asr_agreement_is_not_page_judged() -> None:
    assert "asr_verified" in STATUSES
    doc = _coverage({"aud": "judged"})
    assert doc["status_counts"]["asr_verified"] == 1
    assert doc["status_counts"]["judged"] == 0
    assert doc["cards"][0]["status"] == "asr_verified"
    assert _coverage({"aud": "review"})["cards"][0]["status"] == "review"


def test_corrupt_asr_bundle_is_logged_not_silent(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    class _Log:
        def warning(self, event: str, **_kw: object) -> None:
            seen.append(event)

    monkeypatch.setattr(build_qc_coverage, "log", _Log())
    bad = tmp_path / "asr.json"
    bad.write_text("{not json")
    assert build_qc_coverage._asr_diff_status(bad, []) == {}
    assert seen == ["asr_diff.bundle.unreadable"]


def test_an_out_of_range_agreement_is_never_judged() -> None:
    for bad in (1.5, -0.1, float("inf"), float("nan")):
        bundle = {"cards": [{"card_id": CARD, "status": "judged", "agreement": bad,
                             "threshold": 0.9, "min_words": 20}]}
        assert build_asr_diff_bundle.as_status_map(bundle) == {CARD: "review"}, bad
