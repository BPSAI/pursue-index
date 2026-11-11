"""The autopilot result document validates against its vendored schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.tranche_autopilot import AutopilotConfig, ExitCode, run_autopilot
from pursue_index.tranche_autopilot.result import schema_path
from pursue_index.tranche_autopilot.runner import CommandResult
from pursue_index.tranche_ready.schema import load_schema, validate
from tests.support.autopilot_fakes import SHA, FakeRunner, make_checkout, receipt, with_bucket


def _schema() -> dict:
    return load_schema(schema_path())


def _doc(tmp_path: Path, repo: Path, runner: FakeRunner, sha: str = SHA) -> tuple[int, dict]:
    (tmp_path / "root").mkdir(exist_ok=True)
    out = tmp_path / "result.json"
    code = run_autopilot(AutopilotConfig(sha, out, repo, runner,
                                         {"PURSUE_DATA_ROOT": str(tmp_path / "root")},
                                         lambda _r: 0))
    return code, json.loads(out.read_text())


def _gate_fail(runner: FakeRunner) -> FakeRunner:
    runner.handlers[("make", "ship-ready")] = lambda a, c: CommandResult(2, "", "red")
    return runner


@pytest.mark.parametrize("case", ["done", "lease", "ineligible", "gate", "bad-sha"])
def test_every_outcome_is_schema_valid(tmp_path: Path, case: str) -> None:
    doc_in = {
        "lease": with_bucket(receipt(), "new_content", [{"new_card_id": "n"}]),
        "ineligible": with_bucket(receipt(), "removed", [{"card_id": "r"}]),
    }.get(case, receipt())
    repo = make_checkout(tmp_path, doc_in)
    runner = _gate_fail(FakeRunner(repo)) if case == "gate" else FakeRunner(repo)
    code, doc = _doc(tmp_path, repo, runner, sha="nope" if case == "bad-sha" else SHA)
    assert validate(doc, _schema()) == []
    assert doc["exit_code"] == code


def test_schema_rejects_a_drifted_document(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    _code, doc = _doc(tmp_path, repo, FakeRunner(repo))
    doc["exit_code"] = 1
    doc["extra"] = True
    doc["steps"][0]["status"] = "maybe"
    fields = {e.field for e in validate(doc, _schema())}
    assert {"exit_code", "extra", "steps/0/status"} <= fields


def test_cli_exits_with_the_engine_code_and_writes_the_result(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    out = tmp_path / "cli-result.json"
    result = CliRunner().invoke(app, ["tranche", "autopilot", "--tranche", "not-a-sha",
                                      "--result", str(out), "--repo-root", str(repo)])
    assert result.exit_code == ExitCode.PRECONDITION
    doc = json.loads(out.read_text())
    assert doc["outcome"] == "precondition-missing"
    assert validate(doc, _schema()) == []
