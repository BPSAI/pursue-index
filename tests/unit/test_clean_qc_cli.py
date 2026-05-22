"""Smoke tests for the ``pursue clean qc run`` CLI command.

Mocks the runner so we test argv parsing + manifest filtering, not the
Anthropic layer (covered by test_clean_qc_judge.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from pursue_index.cli.clean_cli import clean_app
from pursue_index.clean.qc import runner as qc_runner

cli_runner = CliRunner()


def _write_manifest(path: Path, card_ids: list[str]) -> None:
    cards = [
        {
            "card_id": cid, "title": f"card {cid}", "agency": "FBI",
            "asset_type": "PDF", "asset_url": f"https://example.test/{cid}.pdf",
            "release_date": "2025-01-01", "redacted": False, "raw": {},
        }
        for cid in card_ids
    ]
    path.write_text(json.dumps({
        "fetched_at": "2025-01-01T00:00:00Z",
        "source_url": "https://example.test/",
        "csv_sha256": "x" * 64,
        "cards": cards,
    }))


def test_qc_run_dispatches_runner_per_card(monkeypatch, tmp_path: Path) -> None:
    """Smoke: invoke `pursue clean qc run` and verify the runner is
    called once per card with the expected paths."""
    manifest_path = tmp_path / "m.json"
    _write_manifest(manifest_path, ["aaaa", "bbbb"])

    fake_run_card = MagicMock(return_value=qc_runner.CardQcReport(
        card_id="aaaa", pages_graded=2, pages_skipped=0,
        pages_skipped_judge=0, cost_usd=0.10,
        input_tokens=3000, output_tokens=800,
    ))
    monkeypatch.setattr(qc_runner, "run_card", fake_run_card)

    # Point settings.ocr_dir at a tmp tree so the CLI doesn't read NAS.
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)

    # The CLI skips cards without pages_cleaned.jsonl on disk — create
    # stubs so the runner actually dispatches per card.
    for cid in ("aaaa", "bbbb"):
        (tmp_path / "ocr" / cid).mkdir(parents=True, exist_ok=True)
        (tmp_path / "ocr" / cid / "pages_cleaned.jsonl").write_text("")

    result = cli_runner.invoke(clean_app, [
        "qc", "run",
        "--manifest", str(manifest_path),
        "--budget-usd", "0.50",
    ])
    assert result.exit_code == 0, result.output
    assert fake_run_card.call_count == 2


def test_qc_run_dry_run_does_not_call_runner(monkeypatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "m.json"
    _write_manifest(manifest_path, ["aaaa"])
    fake_run_card = MagicMock()
    monkeypatch.setattr(qc_runner, "run_card", fake_run_card)
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)

    result = cli_runner.invoke(clean_app, [
        "qc", "run",
        "--manifest", str(manifest_path),
        "--dry-run",
    ])
    assert result.exit_code == 0
    assert fake_run_card.call_count == 0
    assert "DRY-RUN" in result.output or "dry" in result.output.lower()
