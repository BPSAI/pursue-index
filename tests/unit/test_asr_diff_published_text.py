"""An asr_verified card is bound to the transcript text pages.json publishes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pursue_index.clean.qc.coverage import classify_cards
from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_asr_diff_bundle  # type: ignore[import-not-found] # noqa: E402
import build_qc_coverage  # type: ignore[import-not-found] # noqa: E402

CARD = "a9" * 8
TEXT = "the pilot reported a bright light"


def _card_dir(root: Path, text: str = TEXT) -> Path:
    d = root / CARD
    d.mkdir(parents=True, exist_ok=True)
    (d / "pages.jsonl").write_text(json.dumps({"page": 1, "text": text}) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "status": "ok", "rows": [{"row_key": ""}], "finished_at": "v1",
    }))
    return d


def _bundle(root: Path) -> dict:
    d = _card_dir(root)
    runner.run_row(
        card_id=CARD, row_key="", engine_a="a", engine_b="b", text_a=TEXT,
        audio_path=d / "x.wav", sidecar_path=d / sidecar.SIDECAR_FILE,
        second_engine_fn=lambda _p: TEXT, audio_duration_s=60.0,
        rate_usd_per_minute=0.01, budget=runner.AsrDiffBudget(5.0),
    )
    return build_asr_diff_bundle.build(ocr_dir=root, card_ids=[CARD])


def _write(tmp_path: Path, bundle: dict) -> Path:
    path = tmp_path / "asr.json"
    path.write_text(json.dumps(bundle))
    return path


def test_the_bundle_records_a_digest_of_the_transcript_pages(tmp_path: Path) -> None:
    entry = _bundle(tmp_path / "ocr")["cards"][0]
    assert entry["pages_digest"] == sidecar.pages_digest([(1, TEXT)])


def test_a_verdict_for_the_published_text_is_kept(tmp_path: Path) -> None:
    path = _write(tmp_path, _bundle(tmp_path / "ocr"))
    pages = [{"card_id": CARD, "page": 1, "text": TEXT}]
    assert build_qc_coverage._asr_diff_status(path, pages) == {CARD: "judged"}


def test_a_verdict_for_different_published_text_is_dropped(tmp_path: Path) -> None:
    path = _write(tmp_path, _bundle(tmp_path / "ocr"))
    pages = [{"card_id": CARD, "page": 1, "text": TEXT + " and more"}]
    assert build_qc_coverage._asr_diff_status(path, pages) == {}


def test_a_verdict_with_no_digest_is_dropped(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "ocr")
    del bundle["cards"][0]["pages_digest"]
    pages = [{"card_id": CARD, "page": 1, "text": TEXT}]
    assert build_qc_coverage._asr_diff_status(_write(tmp_path, bundle), pages) == {}


def test_a_review_verdict_is_kept_even_if_the_text_changed(tmp_path: Path) -> None:
    bundle = {"cards": [{"card_id": CARD, "status": "review", "agreement": 0.2,
                         "threshold": 0.9, "min_words": 10, "pages_digest": "stale"}]}
    pages = [{"card_id": CARD, "page": 1, "text": "other"}]
    assert build_qc_coverage._asr_diff_status(_write(tmp_path, bundle), pages) == {CARD: "review"}


def test_a_card_with_no_published_text_is_never_asr_verified() -> None:
    manifest = {"csv_sha256": "c" * 64, "fetched_at": "2026-09-01T00:00:00+00:00",
                "cards": [{"card_id": "aud", "asset_type": "AUD"}]}
    bundle = {"cards": []}
    pages = [{"card_id": "aud", "page": 1, "text": "   "}]
    statuses = classify_cards(manifest, bundle, pages, {"card_ids": []}, {},
                              asr_diff_status={"aud": "judged"})
    assert statuses["aud"] == "no_text"


def test_a_failed_second_engine_call_still_spends_against_the_cap(tmp_path: Path) -> None:
    budget = runner.AsrDiffBudget(cap_usd=5.0)

    def boom(_p: Path) -> str:
        raise RuntimeError("vendor error")

    with pytest.raises(RuntimeError):
        runner.run_row(
            card_id=CARD, row_key="", engine_a="a", engine_b="b", text_a=TEXT,
            audio_path=tmp_path / "x.wav", sidecar_path=tmp_path / sidecar.SIDECAR_FILE,
            second_engine_fn=boom, audio_duration_s=60.0, rate_usd_per_minute=1.0,
            budget=budget,
        )
    assert budget.spent_usd == pytest.approx(1.0)


def test_a_comparison_made_before_the_pages_changed_is_not_published(tmp_path: Path) -> None:
    root = tmp_path / "ocr"
    _bundle(root)
    # pages.jsonl changes after the comparison ran (meta version untouched)
    (root / CARD / "pages.jsonl").write_text(json.dumps({"page": 1, "text": TEXT + " more"}) + "\n")
    assert build_asr_diff_bundle.build(ocr_dir=root, card_ids=[CARD])["cards"] == []


def test_the_runner_records_the_pages_digest_it_compared_against(tmp_path: Path) -> None:
    root = tmp_path / "ocr"
    _bundle(root)
    row = sidecar.load_existing(root / CARD / sidecar.SIDECAR_FILE)[""]
    assert row["pages_digest"] == sidecar.pages_digest([(1, TEXT)])
