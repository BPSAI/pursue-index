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
    """A minimal but valid manifest with cards matching the fixture.

    Three cards cover the matched URLs in
    ``tests/fixtures/atlas_join_sample.jsonl``; the fixture's lone
    orphan record (1/5 = 20% miss) sits comfortably under the
    operational miss-rate ceiling (50%).
    """
    p = tmp_path / "manifest.json"
    p.write_text(
        '{"source_url": "https://example.com/x.csv",'
        ' "fetched_at": "2026-05-08T00:00:00Z",'
        ' "csv_sha256": "deadbeef",'
        ' "cards": ['
        ' {"card_id": "ff30c985595153f3",'
        '  "title": "Test", "asset_type": "PDF", "agency": "FBI",'
        '  "asset_url": '
        '"https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf"},'
        ' {"card_id": "702e3997667da8b9",'
        '  "title": "Test2", "asset_type": "PDF", "agency": "FBI",'
        '  "asset_url": '
        '"https://www.war.gov/medialink/ufo/release_1/065uap00099.pdf"},'
        ' {"card_id": "bbf7124aa3691fc4",'
        '  "title": "Test3", "asset_type": "PDF", "agency": "FBI",'
        '  "asset_url": '
        '"https://www.war.gov/medialink/ufo/release_1/'
        '18_100754_%20general%201946-7_vol_2.pdf"}'
        ' ]}'
    )
    return p


def _build_augment_corpus(tmp_path: Path) -> Path:
    """Stage a corpus + sidecars next to it for the --augment-from test.

    The corpus's ``.sha256`` sidecar is computed from the actual file
    bytes so ``load_atlas_index``'s integrity check (laverna SEC-001)
    passes during the smoke test.
    """
    import hashlib

    augment_dir = tmp_path / "external"
    augment_dir.mkdir()
    corpus = augment_dir / "alex-zhang42-corpus.jsonl"
    fixture_text = (
        Path(__file__).parent.parent / "fixtures" / "atlas_join_sample.jsonl"
    ).read_text()
    corpus.write_text(fixture_text)
    real_sha = hashlib.sha256(fixture_text.encode("utf-8")).hexdigest()
    (augment_dir / "alex-zhang42-corpus.sha256").write_text(
        f"{real_sha}  alex-zhang42-corpus.jsonl\n"
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
         "--augment-miss-rate-threshold", "0.5"],
    )
    assert result.exit_code == 0, result.stdout
    assert captured["augment_lookup"] is not None
    assert ("ff30c985595153f3", 1) in captured["augment_lookup"]
    # Provenance dataset/revision come from sidecars; sha256 is the
    # actual file digest (verified by load_atlas_index).
    prov = captured["augmented_by"]
    assert prov["dataset"] == "alex-zhang42/ufo-pursue-open-atlas"
    assert prov["revision"] == "rev123"
    assert len(prov["sha256"]) == 64


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


def test_pursue_embed_run_rejects_threshold_above_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typer must reject ``--augment-miss-rate-threshold`` >0.5 at the CLI
    boundary (laverna SEC-002): a threshold above 50% silently disables
    the join quality gate and is never operationally justified.
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
    assert result.exit_code != 0
    # Pipeline must NOT have been called when CLI validation rejected.
    assert "augment_lookup" not in captured


def test_pursue_embed_run_raises_on_missing_revision_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provenance is non-negotiable: if either sidecar is missing the
    run must fail loudly (nayru P1) rather than write a half-truth
    ``augmented_by = {revision: '', sha256: ''}`` block to ``index.json``.
    """
    captured: dict[str, Any] = {}
    _patch_pipeline_and_adapter(monkeypatch, captured)
    corpus = _build_augment_corpus(tmp_path)
    # Remove the .revision sidecar — the .sha256 stays so SEC-001 passes.
    (corpus.parent / "alex-zhang42-corpus.revision").unlink()

    manifest = _real_manifest(tmp_path)
    result = runner.invoke(
        app,
        ["embed", "run", "--manifest", str(manifest),
         "--augment-from", str(corpus),
         "--augment-miss-rate-threshold", "0.5"],
    )
    assert result.exit_code != 0
    assert "revision" in result.stdout.lower() or "sidecar" in result.stdout.lower()
