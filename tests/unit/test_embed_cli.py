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


class _FakeAdapter:
    """Stand-in for VoyageAdapter; constructor only — must not be invoked."""

    model = "voyage-3"

    def __init__(self, *_: object, **__: object) -> None:
        pass

    def embed_texts(self, *_: object, **__: object) -> object:
        raise AssertionError("CLI test should not actually embed")


class _Summary:
    embedded = 0
    skipped = 0
    total_tokens = 0
    cards_seen = 0


def _capturing_embed_run(captured: dict[str, Any]) -> Any:
    """Build a fake ``embed_run`` that snapshots its kwargs into ``captured``."""

    def _fake(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _Summary()

    return _fake


def _patch_pipeline_and_adapter(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    """Wire up the standard fakes for both Voyage and embed_run."""
    from pursue_index.embed import pipeline as embed_pipeline
    from pursue_index.embed import voyage as voyage_mod

    monkeypatch.setattr(embed_pipeline, "embed_run", _capturing_embed_run(captured))
    monkeypatch.setattr(voyage_mod, "VoyageAdapter", _FakeAdapter)
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-test")


def test_pursue_embed_run_invokes_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)

    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(
        app,
        ["embed", "run", "--manifest", str(manifest),
         "--limit", "5", "--cost-cap-usd", "2.0"],
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


def _real_manifest(tmp_path: Path) -> Path:
    """A minimal but valid manifest with one card so atlas_join has
    something to look up against. The card_id matches the fixture in
    tests/fixtures/atlas_join_sample.jsonl ("ff30c985595153f3").
    """
    p = tmp_path / "manifest.json"
    p.write_text(
        '{"source_url": "https://example.com/x.csv",'
        ' "fetched_at": "2026-05-08T00:00:00Z",'
        ' "csv_sha256": "deadbeef",'
        ' "cards": [{'
        '   "card_id": "ff30c985595153f3",'
        '   "title": "Test",'
        '   "asset_type": "PDF",'
        '   "agency": "FBI",'
        '   "asset_url": '
        '"https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf"'
        ' }]}'
    )
    return p


def _build_augment_corpus(tmp_path: Path) -> Path:
    """Stage a corpus + sidecars next to it for the --augment-from test."""
    augment_dir = tmp_path / "external"
    augment_dir.mkdir()
    corpus = augment_dir / "alex-zhang42-corpus.jsonl"
    fixture_text = (
        Path(__file__).parent.parent / "fixtures" / "atlas_join_sample.jsonl"
    ).read_text()
    corpus.write_text(fixture_text)
    (augment_dir / "alex-zhang42-corpus.sha256").write_text(
        "abc123def  alex-zhang42-corpus.jsonl\n"
    )
    (augment_dir / "alex-zhang42-corpus.revision").write_text("rev123\n")
    return corpus


def test_pursue_embed_run_passes_augment_from_path_to_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``--augment-from`` set, the CLI must build the atlas join
    and pass both ``augment_lookup`` and ``augmented_by`` provenance
    (dataset/revision/sha256) into ``embed_run``.
    """
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)
    corpus = _build_augment_corpus(tmp_path)

    manifest = _real_manifest(tmp_path)
    result = runner.invoke(
        app,
        ["embed", "run", "--manifest", str(manifest),
         "--augment-from", str(corpus),
         "--augment-miss-rate-threshold", "1.0"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["augment_lookup"] is not None
    assert ("ff30c985595153f3", 1) in captured["augment_lookup"]
    assert captured["augmented_by"] == {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": "rev123",
        "sha256": "abc123def",
    }


def test_pursue_embed_run_no_augment_flag_means_no_augment_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--augment-from``, the pipeline gets ``augment_lookup=None``
    so existing un-augmented runs are unchanged.
    """
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)

    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(app, ["embed", "run", "--manifest", str(manifest)])
    assert result.exit_code == 0, result.stdout
    assert captured.get("augment_lookup") is None
    assert captured.get("augmented_by") is None
