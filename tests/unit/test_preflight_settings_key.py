"""The OCR preflights accept a key held only in settings/.env (dummy keys only)."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import SecretStr

from pursue_index.config import settings

from . import test_ingest_run_from_diff as base

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import ship_preflight_ocr  # type: ignore[import-not-found]  # noqa: E402


def test_from_diff_spend_accepts_settings_only_key(tmp_path, monkeypatch) -> None:
    diff_dir = tmp_path / "plans"
    base._write_diff(diff_dir, base._TRANCHE, base._new_content_two_cards())
    snapshot = tmp_path / "snap.json"
    snapshot.write_text("{}", encoding="utf-8")
    manifest = base._write_manifest(tmp_path)
    base._patch_gate_and_promote(monkeypatch, snapshot)
    base._patch_stage_executors(monkeypatch, {})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("dummy-settings-key"))
    res = base.runner.invoke(
        base.ingest_app,
        [*base._common_args(diff_dir, manifest, snapshot), "--from-diff",
         "--engine", "llm-dots", "--concurrency", "8",
         "--worklist", str(tmp_path / "w.txt")],
    )
    assert res.exit_code == 0, res.output


def test_ship_preflight_script_accepts_settings_only_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("dummy-settings-key"))
    argv = ["--engine", "llm-dots", "--concurrency", "8"]
    assert ship_preflight_ocr.main(argv) == 0


def test_ship_preflight_script_refuses_with_no_key_anywhere(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    argv = ["--engine", "llm-dots", "--concurrency", "8"]
    assert ship_preflight_ocr.main(argv) == 1
