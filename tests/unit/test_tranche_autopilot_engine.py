"""Step order, exit codes and the result document of ``tranche autopilot``.

Every run uses a tmp git checkout and ``FakeRunner``: no release command
really runs, nothing touches the network or the real data root.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pursue_index.poll_freshness import PollCheckError
from pursue_index.tranche_autopilot import AutopilotConfig, ExitCode, run_autopilot
from pursue_index.tranche_autopilot.runner import CommandResult
from pursue_index.tranche_autopilot.steps import STEP_NAMES
from tests.support.autopilot_fakes import (
    SHA,
    FakeRunner,
    make_checkout,
    receipt,
    with_bucket,
    write_av_worklist,
    write_pdf_worklist,
)


def _run(tmp_path: Path, repo: Path, runner: FakeRunner, *, behind=lambda _r: 0,
         sha: str = SHA, data_root: Path | None = None) -> tuple[int, dict]:
    root = data_root if data_root is not None else tmp_path / "data-root"
    root.mkdir(exist_ok=True)
    out = tmp_path / "out" / "result.json"
    code = run_autopilot(AutopilotConfig(
        tranche_sha=sha, result_path=out, repo_root=repo, runner=runner,
        env={"PURSUE_DATA_ROOT": str(root)}, behind=behind,
    ))
    return code, json.loads(out.read_text())


def _steps(doc: dict) -> dict[str, dict]:
    return {s["name"]: s for s in doc["steps"]}


def test_happy_path_runs_every_step_in_order_and_commits(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner)

    assert code == ExitCode.DONE == 10
    assert doc["outcome"] == "done-needs-operator"
    assert runner.release_calls() == [
        ["pursue", "ingest", "check", "--tranche", SHA],
        ["pursue", "ingest", "approve", "--tranche", SHA, "--note",
         runner.release_calls()[1][-1]],
        ["pursue", "ingest", "run", "--tranche", SHA, "--from-diff", "--dry-run"],
        ["pursue", "storage", "verify"],
        ["pursue", "ingest", "run", "--tranche", SHA],
        ["make", "ship-ready"],
        ["npm", "run", "test"],
    ]
    assert "autopilot" in runner.release_calls()[1][-1]
    assert [s["name"] for s in doc["steps"]] == list(STEP_NAMES)
    statuses = {n: s["status"] for n, s in _steps(doc).items()}
    assert statuses.pop("ocr-preflight") == "skipped"
    assert set(statuses.values()) == {"ok"}
    assert all(s["duration_s"] >= 0 for s in doc["steps"])

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()
    assert doc["promote_commits"] == [head]
    msg = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=repo, capture_output=True,
                         text=True, check=True).stdout
    assert msg.startswith(f"release: promote tranche {SHA[:12]} (metadata-only)")
    assert "Co-Authored-By" not in msg
    assert doc["changed_paths"]["paths"] == ["data/ingest-worklist.txt",
                                             "data/manifests/latest.json"]
    assert doc["changed_paths"]["by_top_dir"] == {"data": 2}
    assert any("push --set-upstream origin release/t" in line for line in doc["operator_next"])
    assert any(line.startswith("gh pr create") for line in doc["operator_next"])
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                            text=True, check=True).stdout
    assert status == ""


def test_web_tests_run_in_the_web_directory(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    seen: list[Path] = []
    runner = FakeRunner(repo)
    runner.handlers[("npm", "run", "test")] = lambda a, c: (seen.append(c), CommandResult(0))[1]
    _run(tmp_path, repo, runner)
    assert seen == [repo / "web"]


def test_already_approved_skips_approve(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.handlers[("pursue", "ingest", "check")] = lambda a, c: CommandResult(0, "approved")
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert _steps(doc)["approve"]["status"] == "skipped"
    assert not any(c[:3] == ["pursue", "ingest", "approve"] for c in runner.calls)


@pytest.mark.parametrize("sha", ["AB" * 32, "ab" * 31, "zz" * 32, "", "ab" * 32 + "\n"])
def test_bad_sha_is_refused_before_anything_runs(tmp_path: Path, sha: str) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner, sha=sha)
    assert code == ExitCode.PRECONDITION == 40
    assert runner.calls == []
    assert doc["tranche_sha"] is None


def test_missing_receipt_is_a_missing_precondition(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, None)
    code, doc = _run(tmp_path, repo, FakeRunner(repo))
    assert code == ExitCode.PRECONDITION
    assert "receipt missing" in doc["message"]


def test_dirty_tree_is_refused(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    (repo / "stray.txt").write_text("x")
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.PRECONDITION
    assert "not clean" in doc["message"]
    assert runner.release_calls() == []


def test_main_branch_is_refused(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt(), branch="main")
    code, _doc = _run(tmp_path, repo, FakeRunner(repo))
    assert code == ExitCode.PRECONDITION


def test_result_inside_checkout_is_refused(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    code = run_autopilot(AutopilotConfig(
        tranche_sha=SHA, result_path=repo / "result.json", repo_root=repo,
        runner=FakeRunner(repo), env={}, behind=lambda _r: 0))
    assert code == ExitCode.PRECONDITION


def test_ineligible_receipt_exits_21_without_running_steps(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, with_bucket(receipt(), "removed", [{"card_id": "r"}]))
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.INELIGIBLE == 21
    assert doc["outcome"] == "refused-ineligible"
    assert doc["eligibility"]["verdict"] == "ineligible"
    assert runner.release_calls() == []


def test_content_receipt_exits_20_without_running_steps(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, with_bucket(receipt(), "new_content", [{"new_card_id": "n"}]))
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.NEEDS_LEASE == 20
    assert doc["outcome"] == "refused-needs-lease"
    assert runner.release_calls() == []


@pytest.mark.parametrize("kind", ["pdf", "av"])
def test_non_empty_worklist_after_dry_run_needs_a_lease(tmp_path: Path, kind: str) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def dry_run(argv, cwd):
        write_pdf_worklist(repo, SHA, ["0123456789abcdef"] if kind == "pdf" else [])
        if kind == "av":
            write_av_worklist(repo, SHA[:12], ["fedcba9876543210"])
        return CommandResult(0)

    runner.dry_run = dry_run
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.NEEDS_LEASE
    assert doc["failed_step"] == "dry-run-scope"
    assert ["pursue", "storage", "verify"] not in runner.calls


def test_leftover_av_worklist_for_another_tranche_is_ignored(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)

    def dry_run(argv, cwd):
        write_pdf_worklist(repo, SHA)
        write_av_worklist(repo, "0" * 12, ["fedcba9876543210"])
        return CommandResult(0)

    runner.dry_run = dry_run
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.DONE
    assert "leftover" in _steps(doc)["dry-run-scope"]["detail"]


def test_dry_run_that_leaves_no_worklist_for_this_tranche_fails_the_gate(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.dry_run = lambda a, c: CommandResult(0)  # leaves the seeded "old" header
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "dry-run-scope"


@pytest.mark.parametrize("prefix,step", [
    (("pursue", "ingest", "approve"), "approve"),
    (("pursue", "storage", "verify"), "storage-verify"),
    (("make", "ship-ready"), "ship-ready"),
    (("npm", "run", "test"), "web-tests"),
])
def test_gate_failure_exits_30_naming_the_step(tmp_path: Path, prefix, step: str) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.handlers[prefix] = lambda a, c: CommandResult(2, "", "boom")
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED == 30
    assert doc["failed_step"] == step
    assert step in doc["message"]
    assert _steps(doc)[step]["exit_code"] == 2
    assert doc["promote_commits"] == []
    assert doc["operator_next"] == []
    later = list(STEP_NAMES)[list(STEP_NAMES).index(step) + 1:]
    assert all(_steps(doc)[n]["status"] == "not-run" for n in later)


def test_promote_failure_exits_30(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.promote = lambda a, c: CommandResult(1, "", "builder failure")
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "promote"


def test_unexpected_ingest_check_error_fails_approve(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.handlers[("pursue", "ingest", "check")] = lambda a, c: CommandResult(4, "", "x")
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "approve"


@pytest.mark.parametrize("how", ["unset", "missing"])
def test_data_root_preflight_exits_40_before_promote(tmp_path: Path, how: str) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    env = {} if how == "unset" else {"PURSUE_DATA_ROOT": str(tmp_path / "nope")}
    out = tmp_path / "r.json"
    code = run_autopilot(AutopilotConfig(SHA, out, repo, runner, env, lambda _r: 0))
    doc = json.loads(out.read_text())
    assert code == ExitCode.PRECONDITION
    assert doc["failed_step"] == "data-root-preflight"
    assert runner.release_calls() == []  # refused before anything is approved


def test_promote_leaving_no_changes_fails_commit(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    runner.dry_run = lambda a, c: CommandResult(0)
    write_pdf_worklist(repo, SHA)
    subprocess.run(["git", "commit", "-qam", "worklist"], cwd=repo, check=True)
    runner.promote = lambda a, c: CommandResult(0)
    code, doc = _run(tmp_path, repo, runner)
    assert code == ExitCode.GATE_FAILED
    assert doc["failed_step"] == "commit"


def test_behind_at_start_is_superseded(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    code, doc = _run(tmp_path, repo, runner, behind=lambda _r: 2)
    assert code == ExitCode.INELIGIBLE
    assert doc["outcome"] == "refused-superseded"
    assert runner.release_calls() == []


def test_freshness_unknown_at_start_is_a_missing_precondition(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())

    def broken(_r):
        raise PollCheckError("not fetched")

    code, _doc = _run(tmp_path, repo, FakeRunner(repo), behind=broken)
    assert code == ExitCode.PRECONDITION


def test_poller_moving_during_the_run_is_superseded(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    counts = iter([0, 1])
    code, doc = _run(tmp_path, repo, FakeRunner(repo), behind=lambda _r: next(counts))
    assert code == ExitCode.INELIGIBLE
    assert doc["outcome"] == "refused-superseded"
    assert doc["failed_step"] == "freshness-recheck"
    assert len(doc["promote_commits"]) == 1  # the local commit stands; nothing published
    assert doc["operator_next"] == []


def test_children_get_the_configured_env(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    _run(tmp_path, repo, runner)
    envs = [e for c, e in zip(runner.calls, runner.envs, strict=True) if c[0] != "git"]
    assert envs and all(e and "PURSUE_DATA_ROOT" in e for e in envs)


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
