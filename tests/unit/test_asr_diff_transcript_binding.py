"""A comparison is bound to the transcript it saw, and the bundle is
rebuilt additively and tolerates one bad entry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pursue_index.transcribe import asr_diff_runner as runner
from pursue_index.transcribe import asr_diff_sidecar as sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_asr_diff_bundle  # type: ignore[import-not-found] # noqa: E402

C1 = "e1" * 8
C2 = "e2" * 8


def _meta(card_dir: Path, finished_at: str) -> None:
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "x"}) + "\n")
    (card_dir / "meta.json").write_text(json.dumps({
        "status": "ok", "rows": [{"row_key": ""}], "finished_at": finished_at,
    }))


def _compare(card_dir: Path, text: str = "one two three") -> None:
    runner.run_row(
        card_id=card_dir.name, row_key="", engine_a="a", engine_b="b", text_a=text,
        audio_path=card_dir / "x.wav", sidecar_path=card_dir / sidecar.SIDECAR_FILE,
        second_engine_fn=lambda _p: text, audio_duration_s=60.0,
        rate_usd_per_minute=0.01, budget=runner.AsrDiffBudget(10.0),
    )


def _bundle_cards(root: Path, ids: list[str]) -> list[dict]:
    return build_asr_diff_bundle.build(ocr_dir=root, card_ids=ids)["cards"]


def test_a_comparison_of_the_current_transcript_is_published(tmp_path: Path) -> None:
    _meta(tmp_path / C1, "t1")
    _compare(tmp_path / C1)
    assert [(c["card_id"], c["status"]) for c in _bundle_cards(tmp_path, [C1])] == [(C1, "judged")]


def test_a_retranscribed_card_drops_its_old_comparison(tmp_path: Path) -> None:
    _meta(tmp_path / C1, "t1")
    _compare(tmp_path / C1)
    _meta(tmp_path / C1, "t2")  # engine A ran again: new transcript version
    assert _bundle_cards(tmp_path, [C1]) == []


def test_the_runner_compares_again_after_a_retranscription(tmp_path: Path) -> None:
    _meta(tmp_path / C1, "t1")
    _compare(tmp_path / C1)
    _meta(tmp_path / C1, "t2")
    _compare(tmp_path / C1)
    assert [c["card_id"] for c in _bundle_cards(tmp_path, [C1])] == [C1]


def test_should_skip_checks_the_transcript_version_when_known() -> None:
    row = {"engine_a": "a", "engine_b": "b", "transcript_version": "t1"}
    assert sidecar.should_skip(row, engine_a="a", engine_b="b", transcript_version="t1")
    assert not sidecar.should_skip(row, engine_a="a", engine_b="b", transcript_version="t2")


def test_rebuilding_for_new_cards_keeps_previously_published_ones() -> None:
    old = {"cards": [{"card_id": C1, "status": "review"}, {"card_id": C2, "status": "judged"}]}
    new = {"cards": [{"card_id": "f3" * 8, "status": "judged"}]}
    merged = build_asr_diff_bundle.merge_bundles(old, new, requested=["f3" * 8, C2])
    ids = [c["card_id"] for c in merged["cards"]]
    assert ids == sorted([C1, "f3" * 8])  # C2 was requested and no longer qualifies


def test_one_malformed_entry_does_not_discard_the_others() -> None:
    bundle = {"cards": [
        "not-a-dict",
        {"card_id": C1, "status": "judged", "agreement": 0.97, "threshold": 0.9, "min_words": 20},
    ]}
    assert build_asr_diff_bundle.as_status_map(bundle) == {C1: "judged"}
