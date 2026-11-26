"""NTRS claims file: refused when stale, written atomically, kept on abort."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pursue_index import ntrs_source
from pursue_index.cli.provenance_cli import provenance_app
from pursue_index.ntrs_claims_load import (
    StaleNtrsClaimsError,
    claims_for_manifest,
    read_ntrs_claims,
)
from tests.support.ntrs_fakes import TODAY, Net, Resp, card, variant

EARLY = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")


def _manifest(sha: str = "a" * 64) -> dict[str, Any]:
    return {"cards": [card()], "csv_sha256": sha, "source_url": "https://example.test/m"}


def _repo(root: Path, manifest: dict[str, Any]) -> None:
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "data" / "manifests" / "latest.json").write_text(json.dumps(manifest))


def _run(root: Path, net: Net) -> int:
    return ntrs_source.run(root, net.fetcher(), TODAY)


def test_loader_keeps_the_manifest_markers(tmp_path: Path) -> None:
    _repo(tmp_path, _manifest())
    _run(tmp_path, Net(Resp(200, EARLY)))
    stored = read_ntrs_claims(tmp_path)
    assert stored is not None
    assert stored.csv_sha256 == "a" * 64
    assert stored.source_manifest == "https://example.test/m"


def test_matching_shas_apply_the_claims(tmp_path: Path) -> None:
    _repo(tmp_path, _manifest())
    _run(tmp_path, Net(Resp(200, EARLY)))
    claims = claims_for_manifest(tmp_path, _manifest())
    assert [c.card_id for c in claims] == ["c-apollo12"]


def test_mismatched_shas_refuse_the_claims_naming_both(tmp_path: Path) -> None:
    _repo(tmp_path, _manifest())
    _run(tmp_path, Net(Resp(200, EARLY)))
    with pytest.raises(StaleNtrsClaimsError) as err:
        claims_for_manifest(tmp_path, _manifest("b" * 64))
    assert "a" * 64 in str(err.value)
    assert "b" * 64 in str(err.value)


def test_a_missing_file_means_no_claims(tmp_path: Path) -> None:
    assert claims_for_manifest(tmp_path, _manifest()) == []


def test_report_cli_refuses_stale_claims_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, _manifest())
    _run(tmp_path, Net(Resp(200, EARLY)))
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_manifest("b" * 64)))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    result = CliRunner().invoke(provenance_app, ["--manifest", str(other)])
    assert result.exit_code != 0
    assert "a" * 64 in result.output
    assert "b" * 64 in result.output


def test_report_cli_applies_matching_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(tmp_path, _manifest())
    _run(tmp_path, Net(Resp(200, EARLY)))
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    result = CliRunner().invoke(
        provenance_app, ["--manifest", str(tmp_path / "data" / "manifests" / "latest.json")]
    )
    assert result.exit_code == 0, result.output


def _previous(root: Path) -> bytes:
    path = root / ntrs_source.OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"previous": true}\n')
    return path.read_bytes()


def test_an_abort_mid_run_keeps_the_previous_file_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo(tmp_path, {"cards": [card(card_id="a"), card(card_id="b")]})
    before = _previous(tmp_path)
    assert _run(tmp_path, Net(Resp(429))) == 1
    assert (tmp_path / ntrs_source.OUTPUT_PATH).read_bytes() == before
    assert "previous" in capsys.readouterr().out


def test_a_successful_run_replaces_the_file_and_leaves_no_temp(tmp_path: Path) -> None:
    _repo(tmp_path, _manifest())
    _previous(tmp_path)
    assert _run(tmp_path, Net(Resp(200, EARLY))) == 0
    out_dir = (tmp_path / ntrs_source.OUTPUT_PATH).parent
    assert json.loads((out_dir / "ntrs-claims.json").read_text())["claim_count"] == 1
    assert sorted(p.name for p in out_dir.iterdir()) == ["ntrs-claims.json"]


def test_a_failure_while_replacing_keeps_the_previous_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _previous(tmp_path)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        ntrs_source.write_output(tmp_path, {"claims": []})
    out_dir = (tmp_path / ntrs_source.OUTPUT_PATH).parent
    assert (out_dir / "ntrs-claims.json").read_bytes() == before
    assert [p.name for p in out_dir.iterdir()] == ["ntrs-claims.json"]
