"""Every worklist-consuming command refuses a stale/mislabeled worklist
(R7C.1 / #168): ``download``, ``ocr``, ``clean``, ``embed``, ``vision``,
``mirror-pdfs``, ``verify-mirror`` must each exit non-zero -- naming both the
worklist's tranche and the promoted manifest's -- when given a worklist
labeled for a different tranche, or one with no ``# tranche:`` header at all.

This is deliberately ONE parametrized test (over both failure modes and all
seven consumers) rather than seven near-duplicate test functions: the
contract is identical everywhere (``pursue_index.cli.worklist``'s
``require_worklist_tranche``), so a single table of "how do I invoke this
consumer" is the whole test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()

_GOOD_SHA = "a" * 64
_BAD_SHA = "b" * 64


def _write_manifest(path: Path, card_ids: list[str], csv_sha256: str = _GOOD_SHA) -> None:
    m = Manifest(
        source_url="https://example.com/data.csv",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        csv_sha256=csv_sha256,
        cards=[
            CardMetadata(card_id=cid, title="t", asset_type="PDF", agency="a")
            for cid in card_ids
        ],
    )
    save_manifest(m, path)


def _invoke_download(tmp_path: Path, monkeypatch, worklist: Path):
    async def fake_download_all(m):
        return []

    monkeypatch.setattr("pursue_index.download.downloader.download_all", fake_download_all)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    return runner.invoke(
        app, ["download", "run", "--manifest", str(manifest), "--worklist", str(worklist)]
    )


def _invoke_ocr(tmp_path: Path, monkeypatch, worklist: Path):
    async def fake_ocr_all(m, **kwargs):
        return None

    monkeypatch.setattr("pursue_index.ocr.pipeline.ocr_all", fake_ocr_all)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    return runner.invoke(
        app, ["ocr", "run", "--manifest", str(manifest), "--worklist", str(worklist)]
    )


def _invoke_clean(tmp_path: Path, monkeypatch, worklist: Path):
    monkeypatch.setattr("pursue_index.cli.clean_cli.run_card", lambda **kwargs: None)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    return runner.invoke(
        app,
        ["clean", "run", "--manifest", str(manifest), "--worklist", str(worklist),
         "--budget-usd", "5"],
    )


def _invoke_embed(tmp_path: Path, monkeypatch, worklist: Path):
    monkeypatch.setattr("pursue_index.cli.embed_cli._make_embedder", lambda *a, **k: object())
    monkeypatch.setattr(
        "pursue_index.embed.pipeline.embed_run",
        lambda **kwargs: SimpleNamespace(embedded=0, skipped=0, total_tokens=0, cards_seen=0),
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    return runner.invoke(
        app, ["embed", "run", "--manifest", str(manifest), "--worklist", str(worklist)]
    )


def _invoke_vision(tmp_path: Path, monkeypatch, worklist: Path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1"])
    out = tmp_path / "obs"
    return runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--worklist", str(worklist),
         "--out", str(out)],
    )


def _invoke_mirror_pdfs(tmp_path: Path, monkeypatch, worklist: Path):
    monkeypatch.setattr(settings, "manifests_dir", tmp_path)
    _write_manifest(tmp_path / "latest.json", ["c1"])
    return runner.invoke(app, ["storage", "mirror-pdfs", "--worklist", str(worklist)])


def _invoke_verify_mirror(tmp_path: Path, monkeypatch, worklist: Path):
    monkeypatch.setattr(settings, "manifests_dir", tmp_path)
    _write_manifest(tmp_path / "latest.json", ["c1"])
    return runner.invoke(app, ["storage", "verify-mirror", "--worklist", str(worklist)])


_CONSUMERS = {
    "download": _invoke_download,
    "ocr": _invoke_ocr,
    "clean": _invoke_clean,
    "embed": _invoke_embed,
    "vision": _invoke_vision,
    "mirror-pdfs": _invoke_mirror_pdfs,
    "verify-mirror": _invoke_verify_mirror,
}


@pytest.mark.parametrize("name", sorted(_CONSUMERS))
def test_consumer_refuses_worklist_for_a_different_tranche(name, tmp_path, monkeypatch) -> None:
    invoke = _CONSUMERS[name]
    worklist = tmp_path / "worklist.txt"
    worklist.write_text(f"# tranche: {_BAD_SHA}\nc1\n")

    result = invoke(tmp_path, monkeypatch, worklist)

    assert result.exit_code != 0, f"{name}: expected non-zero exit, got {result.output}"
    assert _GOOD_SHA in result.output, f"{name}: promoted sha not named: {result.output}"
    assert _BAD_SHA in result.output, f"{name}: worklist sha not named: {result.output}"


@pytest.mark.parametrize("name", sorted(_CONSUMERS))
def test_consumer_refuses_worklist_with_no_header(name, tmp_path, monkeypatch) -> None:
    invoke = _CONSUMERS[name]
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("c1\n")  # no "# tranche: ..." header at all

    result = invoke(tmp_path, monkeypatch, worklist)

    assert result.exit_code != 0, f"{name}: expected non-zero exit, got {result.output}"
    assert _GOOD_SHA in result.output, f"{name}: promoted sha not named: {result.output}"
