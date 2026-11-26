"""The NTRS stage is a production CLI entry, and era bucketing fails closed on stale claims."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pursue_index import ntrs_source
from pursue_index.cli.provenance_cli import provenance_app
from tests.support.ntrs_fakes import Net, Resp, card, variant

EARLY = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
HOSTS_FILE = Path("data") / "provenance" / "ntrs-hosts.json"


def _repo(root: Path, manifest: dict[str, Any]) -> None:
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "data" / "manifests" / "latest.json").write_text(json.dumps(manifest))
    (root / HOSTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / HOSTS_FILE).write_text(json.dumps({"hosts": ["ntrs.nasa.gov"]}))


def _manifest(sha: str = "a" * 64) -> dict[str, Any]:
    return {"cards": [card()], "csv_sha256": sha, "source_url": "https://example.test/m"}


def test_the_ntrs_subcommand_is_registered() -> None:
    names = {c.name for c in provenance_app.registered_commands}
    assert {"report", "ntrs"} <= names


def test_the_ntrs_subcommand_runs_the_search_and_writes_the_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, _manifest())
    net = Net(Resp(200, EARLY))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(ntrs_source, "default_get", net.get)
    result = CliRunner().invoke(provenance_app, ["ntrs"])
    assert result.exit_code == 0, result.output
    written = json.loads((tmp_path / ntrs_source.OUTPUT_PATH).read_text())
    assert written["claim_count"] == 1
    assert net.events.count("get") == 1


def test_the_ntrs_subcommand_exits_non_zero_on_429_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, _manifest())
    net = Net(Resp(429))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(ntrs_source, "default_get", net.get)
    result = CliRunner().invoke(provenance_app, ["ntrs"])
    assert result.exit_code != 0
    assert not (tmp_path / ntrs_source.OUTPUT_PATH).exists()


def test_era_bucketing_main_refuses_stale_claims_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pursue_index import era_bucketing

    _repo(tmp_path, _manifest())
    ntrs_source.run(tmp_path, Net(Resp(200, EARLY)).fetcher(), __import__("datetime").date(2026, 11, 25))
    (tmp_path / "data" / "manifests" / "latest.json").write_text(json.dumps(_manifest("b" * 64)))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    out_path = tmp_path / era_bucketing.OUTPUT_PATH
    assert era_bucketing.main() != 0
    text = capsys.readouterr().out
    assert "a" * 64 in text
    assert "b" * 64 in text
    assert "stale" in text.lower()
    assert not out_path.exists()
