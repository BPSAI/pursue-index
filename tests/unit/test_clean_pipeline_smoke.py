"""End-to-end smoke: runner → sidecar → build script.

Exercises the data path the operator's real pilot will follow, with the
Anthropic client mocked out. Verifies provenance fields round-trip and
``pages-cleaned.json`` has the expected shape for the web UI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_pages_cleaned  # type: ignore[import-not-found] # noqa: E402

import pytest

from pursue_index.clean import client as clean_client
from pursue_index.clean import runner as clean_runner


def test_runner_then_build_emits_web_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three-page input → sidecar with provenance → pages-cleaned.json."""
    ocr_dir = tmp_path / "ocr"
    card_dir = ocr_dir / "card_abc"
    card_dir.mkdir(parents=True)
    pages_path = card_dir / "pages.jsonl"
    pages_path.write_text(
        "\n".join(json.dumps({
            "page": i,
            "text": f"raw page {i}\nwith dehy-\nphenated word",
        }) for i in (1, 2, 3)) + "\n"
    )
    sidecar_path = card_dir / "pages_cleaned.jsonl"

    def _fake(raw_text: str, model_id: str):
        return (
            raw_text.replace("dehy-\nphenated", "dehyphenated"),
            clean_client.Usage(
                input_tokens=200, output_tokens=180,
                cache_read_tokens=0, cache_creation_tokens=0,
            ),
        )

    monkeypatch.setattr(clean_runner, "clean_page", _fake)
    report = clean_runner.run_card(
        card_id="card_abc",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=1.0,
        running_cost_usd=0.0,
    )
    assert report.pages_cleaned == 3
    assert sidecar_path.exists()

    # Write a manifest covering the card so the build joins title metadata.
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "cards": [
            {"card_id": "card_abc", "title": "Smoke Card",
             "asset_type": "PDF", "raw": {}},
        ],
    }))
    out_path = tmp_path / "pages-cleaned.json"
    rc = build_pages_cleaned.build(
        ocr_dir=ocr_dir,
        manifest_path=manifest,
        out_path=out_path,
        source_tag="smoke-test",
    )
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["meta"]["model_id"] == "claude-haiku-4-5-20251001"
    assert payload["meta"]["page_count"] == 3
    assert payload["meta"]["cards_covered"] == ["card_abc"]
    for page_row in payload["pages"]:
        assert page_row["title"] == "Smoke Card"
        # Provenance — every page must carry the full tuple.
        for key in (
            "model_id", "prompt_sha256", "input_sha256",
            "output_sha256", "generated_at",
        ):
            assert page_row[key], f"missing {key} in {page_row}"
        # Cleaned text differs from raw in the expected way (dehyphenation).
        assert "dehyphenated" in page_row["text"]
        assert "dehy-" not in page_row["text"]


def test_runner_resumes_from_partial_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second run with the same input is a no-op (full skip)."""
    from pursue_index.clean import prompt as clean_prompt

    ocr_dir = tmp_path / "ocr" / "cardX"
    ocr_dir.mkdir(parents=True)
    pages_path = ocr_dir / "pages.jsonl"
    pages_path.write_text(json.dumps({"page": 1, "text": "stable"}) + "\n")
    sidecar_path = ocr_dir / "pages_cleaned.jsonl"

    def _fake(raw_text: str, model_id: str):
        return "cleaned", clean_client.Usage(50, 40, 0, 0)

    monkeypatch.setattr(clean_runner, "clean_page", _fake)
    # First run: writes one row.
    clean_runner.run_card(
        card_id="cardX",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=1.0,
        running_cost_usd=0.0,
    )
    # Tamper-detect: model must NOT be called the second time.
    def _trip(*_a, **_k):
        raise AssertionError("clean_page must be skipped on resume")
    monkeypatch.setattr(clean_runner, "clean_page", _trip)
    report = clean_runner.run_card(
        card_id="cardX",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=1.0,
        running_cost_usd=0.0,
    )
    assert report.pages_cleaned == 0
    assert report.pages_skipped == 1
    # Sanity: idempotency-key in the sidecar matches the runner's calc.
    rows = [
        json.loads(line) for line in sidecar_path.read_text().splitlines()
        if line.strip()
    ]
    assert rows[0]["idempotency_key"] == clean_prompt.idempotency_key(
        text="stable",
        model_id="claude-haiku-4-5-20251001",
        prompt_sha=clean_prompt.prompt_sha256(),
    )
