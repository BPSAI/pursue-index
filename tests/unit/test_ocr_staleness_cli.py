"""``pursue ocr staleness`` CLI surface (R7C.16 / #171).

Reads ``pages.jsonl`` for every manifest card under ``settings.ocr_dir`` and
flags any card whose ``llm`` rows carry more than one model, or a model
other than the currently operated one. Exit code carries the verdict: 0
clean, 1 when any card is flagged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True))


def _pdf_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="t",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def _write_pages(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_ocr_staleness_flags_mixed_and_passes_uniform(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "ocr_llm_model", "claude-sonnet-4-6")

    mixed, uniform = _pdf_card("mixedcard0001"), _pdf_card("uniformcard01")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [mixed, uniform])

    _write_pages(
        settings.ocr_dir / mixed.card_id / "pages.jsonl",
        [
            {"page": 1, "text": "a", "confidence": 90, "engine": "llm", "model": "claude-sonnet-4-6"},
            {"page": 2, "text": "b", "confidence": 90, "engine": "llm", "model": "claude-opus-4"},
        ],
    )
    _write_pages(
        settings.ocr_dir / uniform.card_id / "pages.jsonl",
        [{"page": 1, "text": "a", "confidence": 90, "engine": "llm", "model": "claude-sonnet-4-6"}],
    )

    result = runner.invoke(app, ["ocr", "staleness", "--manifest", str(manifest_path)])

    assert result.exit_code == 1, result.stdout
    assert "mixedcard0001" in result.stdout
    assert "uniformcard01" not in result.stdout


def test_ocr_staleness_passes_clean_corpus(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_root", tmp_path)
    monkeypatch.setattr(settings, "ocr_llm_model", "claude-sonnet-4-6")

    card = _pdf_card("cleancard00001")
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [card])
    _write_pages(
        settings.ocr_dir / card.card_id / "pages.jsonl",
        [{"page": 1, "text": "a", "confidence": 90, "engine": "llm", "model": "claude-sonnet-4-6"}],
    )

    result = runner.invoke(app, ["ocr", "staleness", "--manifest", str(manifest_path)])

    assert result.exit_code == 0, result.stdout
