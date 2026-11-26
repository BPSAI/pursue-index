"""The NTRS stage is a production CLI entry, and era bucketing leaves stale claims out."""

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
    assert "429" in result.output
    assert not (tmp_path / ntrs_source.OUTPUT_PATH).exists()


def _bucketed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest_sha: str, strip: bool = False) -> dict[str, Any]:
    from pursue_index import era_bucketing

    modern = {**_manifest(), "cards": [card(incident_date="2020")]}
    _repo(tmp_path, _manifest())
    ntrs_source.run(tmp_path, Net(Resp(200, EARLY)).fetcher(), __import__("datetime").date(2026, 11, 25))
    if strip:
        path = tmp_path / ntrs_source.OUTPUT_PATH
        data = json.loads(path.read_text())
        data.pop("csv_sha256", None)
        path.write_text(json.dumps(data))
    (tmp_path / "data" / "manifests" / "latest.json").write_text(json.dumps({**modern, "csv_sha256": manifest_sha}))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    assert era_bucketing.main() == 0
    return json.loads((tmp_path / era_bucketing.OUTPUT_PATH).read_text())


def test_era_bucketing_main_runs_without_stale_claims_and_labels_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _bucketed(tmp_path, monkeypatch, "b" * 64)
    text = capsys.readouterr().out
    assert text.count("NTRS claims not applied") == 1
    assert f"NTRS claims not applied: claims file is for csv {'a' * 64}" in text
    assert out["superseded_by_claim"] == []


def test_era_bucketing_main_applies_matching_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _bucketed(tmp_path, monkeypatch, "a" * 64)
    assert "NTRS claims not applied" not in capsys.readouterr().out
    assert len(out["superseded_by_claim"]) == 1


def test_era_bucketing_main_says_none_for_a_marker_less_claims_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _bucketed(tmp_path, monkeypatch, "a" * 64, strip=True)
    assert "NTRS claims not applied: claims file is for csv <none>" in capsys.readouterr().out
    assert out["superseded_by_claim"] == []
