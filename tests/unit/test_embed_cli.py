"""Smoke tests for the `pursue embed` CLI surface.

We patch the pipeline at the module seam so the CLI test is fast, hermetic,
and doesn't require any provider SDK or API key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app

runner = CliRunner()


def _stub_manifest(tmp_path: Path) -> Path:
    p = tmp_path / "manifest.json"
    p.write_text(
        '{"source_url": "https://example.com/x.csv",'
        ' "fetched_at": "2026-05-08T00:00:00Z",'
        ' "csv_sha256": "deadbeef", "cards": []}'
    )
    return p


def test_pursue_embed_run_invokes_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_embed_run(**kwargs: Any) -> Any:
        captured.update(kwargs)

        class S:
            embedded = 7
            skipped = 0
            total_tokens = 1234
            cards_seen = 3

        return S()

    class FakeAdapter:
        model = "voyage-3"

        def __init__(self, *_: object, **__: object) -> None:
            pass

        def embed_texts(self, *_: object, **__: object) -> object:
            raise AssertionError("CLI test should not actually embed")

    from pursue_index.embed import pipeline as embed_pipeline

    monkeypatch.setattr(embed_pipeline, "embed_run", fake_embed_run)
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-test")
    # CLI imports the adapter lazily via pursue_index.embed.voyage; patch the
    # constructor at that seam.
    from pursue_index.embed import voyage as voyage_mod

    monkeypatch.setattr(voyage_mod, "VoyageAdapter", FakeAdapter)

    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(
        app,
        [
            "embed",
            "run",
            "--manifest",
            str(manifest),
            "--limit",
            "5",
            "--cost-cap-usd",
            "2.0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["limit"] == 5
    assert captured["cost_cap_usd"] == 2.0
    assert captured["embedder"].model == "voyage-3"


def test_pursue_embed_run_errors_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(app, ["embed", "run", "--manifest", str(manifest)])
    assert result.exit_code != 0
    assert "VOYAGE_API_KEY" in result.stdout or "api_key" in result.stdout.lower()
