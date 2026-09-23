"""`pursue storage verify` probes the data root and reports OCR coverage.

``configured`` (an env key resolves) and ``mounted`` (the path actually
answers a ``stat``) are different facts: an unmounted NAS leaves the env var
set, and the derivative builders then silently see an empty tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.storage.data_root import ocr_coverage, probe_data_root

runner = CliRunner()

_R2_ENV = {
    "R2_ACCOUNT_ID": "acct-primary",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "BACKUP_R2_ACCOUNT_ID": "acct-backup",
    "BACKUP_R2_ACCESS_KEY_ID": "bak",
    "BACKUP_R2_SECRET_ACCESS_KEY": "bsk",
}


def _configure(monkeypatch: pytest.MonkeyPatch, root: Path, manifests: Path) -> None:
    for k, v in {**_R2_ENV, "PURSUE_DATA_ROOT": str(root)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(settings, "manifests_dir", manifests)


def _manifest(manifests: Path, card_ids: list[str]) -> None:
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "latest.json").write_text(
        json.dumps({"cards": [{"card_id": c, "title": c, "asset_type": "PDF"}
                              for c in card_ids]})
    )


def _pages(root: Path, card_id: str) -> None:
    card_dir = root / "ocr" / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "pages.jsonl").write_text('{"page": 1, "text": "t"}\n')


def test_probe_mounted_when_dir_exists(tmp_path: Path) -> None:
    probe = probe_data_root({"PURSUE_DATA_ROOT": str(tmp_path)})
    assert probe.configured and probe.mounted


def test_probe_configured_but_absent(tmp_path: Path) -> None:
    probe = probe_data_root({"PURSUE_DATA_ROOT": str(tmp_path / "gone")})
    assert probe.configured and not probe.mounted


def test_probe_file_is_not_a_mount(tmp_path: Path) -> None:
    f = tmp_path / "file"
    f.write_text("x")
    assert not probe_data_root({"PURSUE_DATA_ROOT": str(f)}).mounted


def test_probe_unconfigured() -> None:
    probe = probe_data_root({})
    assert not probe.configured and not probe.mounted


def test_ocr_coverage_counts_manifest_cards_with_pages(tmp_path: Path) -> None:
    _pages(tmp_path, "c1")
    _pages(tmp_path, "not-in-manifest")
    cards = [{"card_id": c} for c in ("c1", "c2", "c3")]
    assert ocr_coverage(tmp_path / "ocr", cards) == (1, 3)


def test_verify_reports_mounted_and_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    _pages(root, "c1")
    _manifest(tmp_path / "manifests", ["c1", "c2"])
    _configure(monkeypatch, root, tmp_path / "manifests")

    res = runner.invoke(app, ["storage", "verify"])

    assert res.exit_code == 0, res.output
    assert "mounted: yes" in res.output
    assert "ocr coverage: 1/2 cards" in res.output
    assert "configured" in res.output


def test_verify_exits_1_when_configured_root_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The data root existed when configured and was removed afterwards."""
    root = tmp_path / "root"
    root.mkdir()
    _manifest(tmp_path / "manifests", ["c1"])
    _configure(monkeypatch, root, tmp_path / "manifests")
    root.rmdir()

    res = runner.invoke(app, ["storage", "verify"])

    assert res.exit_code == 1, res.output
    assert "mounted: no" in res.output
    assert "ocr coverage" in res.output
