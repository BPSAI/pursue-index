"""``scripts/build_asr_diff_bundle.py`` -- aggregate per-row
``asr_diff.jsonl`` sidecars (written by ``asr_diff_runner.run_row``) into
one committed bundle ``qc-coverage``'s build script can read, the same
publish step ``clean-qc-bundle.json`` already uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_asr_diff_bundle  # type: ignore[import-not-found] # noqa: E402


def _write_sidecar(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_a_card_with_one_row_takes_that_rows_status(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "card-1" / "asr_diff.jsonl", [
        {"row_key": "", "engine_a": "assemblyai", "engine_b": "fake-b",
         "status": "judged", "agreement": 0.98},
    ])
    bundle = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=["card-1"])
    assert bundle["cards"] == [{"card_id": "card-1", "status": "judged"}]


def test_a_card_with_several_rows_takes_the_worst_status(tmp_path: Path) -> None:
    """One row flagged for review means the card as a whole isn't clear,
    even though its other row agreed completely."""
    _write_sidecar(tmp_path / "card-2" / "asr_diff.jsonl", [
        {"row_key": "a", "engine_a": "assemblyai", "engine_b": "fake-b",
         "status": "judged", "agreement": 1.0},
        {"row_key": "b", "engine_a": "assemblyai", "engine_b": "fake-b",
         "status": "review", "agreement": 0.5},
    ])
    bundle = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=["card-2"])
    assert bundle["cards"] == [{"card_id": "card-2", "status": "review"}]


def test_a_card_with_no_sidecar_is_omitted(tmp_path: Path) -> None:
    bundle = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=["no-sidecar"])
    assert bundle["cards"] == []


def test_as_status_map_is_card_id_to_status(tmp_path: Path) -> None:
    _write_sidecar(tmp_path / "card-1" / "asr_diff.jsonl", [
        {"row_key": "", "engine_a": "assemblyai", "engine_b": "fake-b",
         "status": "judged", "agreement": 0.98},
    ])
    bundle = build_asr_diff_bundle.build(ocr_dir=tmp_path, card_ids=["card-1"])
    assert build_asr_diff_bundle.as_status_map(bundle) == {"card-1": "judged"}
