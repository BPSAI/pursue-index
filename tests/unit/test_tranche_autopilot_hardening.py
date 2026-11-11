"""Hardening of ``tranche autopilot``: scope preview, commit scope, redaction,
unexpected errors. Same tmp-checkout + ``FakeRunner`` setup as the engine tests.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pursue_index.tranche_autopilot import ExitCode
from pursue_index.tranche_autopilot.runner import CommandResult
from tests.support.autopilot_fakes import (
    SHA,
    FakeRunner,
    make_checkout,
    receipt,
    run_engine,
    steps_by_name,
    write_pdf_worklist,
)

_run = run_engine
_steps = steps_by_name


def _drift_bytes(repo: Path, data_root: Path, card_id: str = "0123456789abcdef") -> None:
    """A registry byte sha that differs from the card's OCR sidecar."""
    (repo / "data" / "asset-bytes-registry.jsonl").write_text(
        json.dumps({"card_id": card_id, "byte_sha256": "1" * 64}) + "\n")
    meta = data_root / "ocr" / card_id / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"pdf_sha256": "2" * 64}))
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "registry"], cwd=repo, check=True)


def test_scope_preview_refuses_before_approval_is_recorded(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    root = tmp_path / "data-root"
    root.mkdir()
    _drift_bytes(repo, root)
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner, data_root=root)
    assert code == ExitCode.NEEDS_LEASE
    assert doc["failed_step"] == "scope-preview"
    assert "1 PDF/IMG" in _steps(doc)["scope-preview"]["detail"]
    assert runner.release_calls() == []


def test_unexpected_error_still_writes_a_result_with_a_documented_code(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def explode(argv, cwd):
        raise RuntimeError("bug")

    runner.handlers[("pursue", "storage", "verify")] = explode
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "storage-verify"
    assert "internal error" in doc["message"]


def test_non_object_receipt_is_a_missing_precondition(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, None)
    path = repo / "data" / "tranche-diffs" / f"tranche-diff-{SHA[:12]}.json"
    path.write_text("[]")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "r"], cwd=repo, check=True)
    code, doc = _run(tmp_path, repo, FakeRunner(repo))
    assert code == ExitCode.PRECONDITION
    assert "not a JSON object" in doc["message"]


def test_changes_outside_data_and_web_are_not_committed(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def ship_ready(argv, cwd):
        (repo / "stray.log").write_text("x")
        return CommandResult(0)

    runner.handlers[("make", "ship-ready")] = ship_ready
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "commit"
    assert "stray.log" in _steps(doc)["commit"]["detail"]
    assert doc["promote_commits"] == []


def test_child_output_is_redacted_in_the_result(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    leak = "ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnop failed; token sk-abcdefghijklmnopqr"
    runner.handlers[("pursue", "storage", "verify")] = lambda a, c: CommandResult(1, "", leak)
    _code, doc = _run(tmp_path, repo, runner)
    detail = _steps(doc)["storage-verify"]["detail"]
    assert "sk-" not in detail
    assert "ANTHROPIC_API_KEY=<redacted>" in detail


def test_new_build_byproducts_are_not_committed(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def web_tests(argv, cwd):
        (repo / "web" / "coverage").mkdir()
        (repo / "web" / "coverage" / "lcov.info").write_text("x")
        return CommandResult(0)

    runner.handlers[("npm", "run", "test")] = web_tests
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert "web/coverage/lcov.info" in _steps(doc)["commit"]["detail"]


def test_new_files_under_site_data_are_committed(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def ship_ready(argv, cwd):
        (repo / "web" / "public" / "data").mkdir(parents=True)
        (repo / "web" / "public" / "data" / "cards.json").write_text("{}")
        return CommandResult(0)

    runner.handlers[("make", "ship-ready")] = ship_ready
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert "web/public/data/cards.json" in doc["changed_paths"]["paths"]


def test_dry_run_refusal_after_this_run_approved_says_so(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def dry_run(argv, cwd):
        write_pdf_worklist(repo, SHA, ["0123456789abcdef"])
        return CommandResult(0)

    runner.dry_run = dry_run
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.NEEDS_LEASE
    assert "autopilot approval" in doc["message"]


@pytest.mark.parametrize("leak", [
    "Authorization: Bearer abcdef0123456789",
    "id AKIAABCDEFGHIJKLMNOP here",
    "fetch https://user:hunter2pass@example.invalid/x failed",
    '{"api_key": "abcdef0123456789"}',
])
def test_more_credential_shapes_are_redacted(leak: str) -> None:
    from pursue_index.tranche_autopilot.result import redact

    out = redact(leak)
    assert not any(s in out for s in ("abcdef0123456789", "AKIAABCDEFGHIJKLMNOP", "hunter2pass"))
