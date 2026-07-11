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
         "--image-observations-index", str(tmp_path / "none.json"),
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


def _stage_obs_index(tmp_path: Path, card_id: str, page: int) -> Path:
    """Write an image-observations index + sidecar; return the index path."""
    import json

    obs = tmp_path / "obs"
    obs.mkdir()
    (obs / "index.json").write_text(
        json.dumps({"schema_version": 1, "card_ids": [card_id]})
    )
    (obs / f"{card_id}.json").write_text(
        json.dumps({
            "card_id": card_id,
            "our_pass": {"model": "claude-opus-4-8"},
            "pages": [{"page": page, "description": "A photograph.",
                       "visible_text": "", "observations": []}],
        })
    )
    return obs / "index.json"


def test_pursue_embed_run_passes_obs_lookup_to_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an image-observations index present, the CLI builds the
    image-only vision-text lookup and passes it into ``embed_run``."""
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)
    obs_index = _stage_obs_index(tmp_path, "ff30c985595153f3", 1)

    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(
        app,
        ["embed", "run", "--manifest", str(manifest),
         "--image-observations-index", str(obs_index)],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["obs_lookup"] is not None
    assert ("ff30c985595153f3", 1) in captured["obs_lookup"]


def test_pursue_embed_run_no_obs_index_means_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-existent image-observations index yields ``obs_lookup=None`` so
    corpora with no image-observations behave exactly as before."""
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)

    manifest = _stub_manifest(tmp_path)
    result = runner.invoke(
        app,
        ["embed", "run", "--manifest", str(manifest),
         "--image-observations-index", str(tmp_path / "none.json")],
    )
    assert result.exit_code == 0, result.stdout
    assert captured.get("obs_lookup") is None
    # The retired augment surface is gone entirely.
    assert "augment_lookup" not in captured
