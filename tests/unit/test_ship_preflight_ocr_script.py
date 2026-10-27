"""``scripts/ship_preflight_ocr.py`` -- the checked-in OCR preflight the
ship-tranche runbook runs instead of inline ``python -c``."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ship_preflight_ocr  # type: ignore[import-not-found] # noqa: E402


def test_preflight_passes_with_the_operated_flags_and_a_key() -> None:
    argv = ["--engine", "llm-dots", "--concurrency", "8"]
    assert ship_preflight_ocr.main(argv, {"ANTHROPIC_API_KEY": "present"}) == 0


def test_preflight_refuses_without_a_key() -> None:
    assert ship_preflight_ocr.main(["--engine", "llm-dots", "--concurrency", "8"], {}) == 1


def test_preflight_refuses_a_retired_engine_or_low_concurrency() -> None:
    env = {"ANTHROPIC_API_KEY": "present"}
    assert ship_preflight_ocr.main(["--engine", "tesseract", "--concurrency", "8"], env) == 1
    assert ship_preflight_ocr.main(["--engine", "llm-dots", "--concurrency", "4"], env) == 1


def test_preflight_reads_the_effective_config_from_the_env_when_flags_are_omitted() -> None:
    stale = {"ANTHROPIC_API_KEY": "k", "PURSUE_OCR_ENGINE": "auto", "PURSUE_OCR_LLM_CONCURRENCY": "8"}
    assert ship_preflight_ocr.main([], stale) == 1
    good = {"ANTHROPIC_API_KEY": "k", "PURSUE_OCR_ENGINE": "llm-dots", "PURSUE_OCR_LLM_CONCURRENCY": "8"}
    assert ship_preflight_ocr.main([], good) == 0
    assert ship_preflight_ocr.main([], {"ANTHROPIC_API_KEY": "k"}) == 1  # nothing configured


def test_runbook_runs_the_script_not_inline_python() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "ship-tranche.md").read_text()
    assert "python scripts/ship_preflight_ocr.py --engine llm-dots --concurrency 8" in text
    assert "python -c" not in text
    assert "Bash(git:*)" not in text
    # A tracked doc grants nothing; the operator-local command carries its own tool grants.
    assert "allowed-tools" not in text


def test_runbook_transcribe_step_uses_only_supported_flags() -> None:
    text = (REPO_ROOT / "docs" / "runbooks" / "ship-tranche.md").read_text()
    step = text[text.index("5d. **Transcribe audio") : text.index("6. **OCR")]
    assert "--worklist" not in step
    assert "--release-date" in step


def test_a_non_ascii_digit_concurrency_is_treated_as_unset_not_a_crash() -> None:
    env = {"ANTHROPIC_API_KEY": "k", "PURSUE_OCR_ENGINE": "llm-dots",
           "PURSUE_OCR_LLM_CONCURRENCY": "٨"}  # Arabic-indic digit eight
    assert ship_preflight_ocr.main([], env) == 1
