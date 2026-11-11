"""Drive one autopilot run and write its result document.

Order: validate the sha; check the checkout (result path outside it, clean
tree, on a branch other than main) and poll freshness; load and assess the
receipt; then the steps in ``steps.STEP_NAMES``. The result is written on
every exit; the return value is the process exit code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.poll_freshness import PollCheckError, commits_behind_on_poll_paths
from pursue_index.tranche_autopilot import steps as rs
from pursue_index.tranche_autopilot.eligibility import Eligibility, ReceiptError, assess
from pursue_index.tranche_autopilot.gitops import GitError, current_branch, is_clean
from pursue_index.tranche_autopilot.outcome import AutopilotStopError, ExitCode, Outcome
from pursue_index.tranche_autopilot.result import (
    SCHEMA_VERSION,
    Step,
    now_iso,
    operator_next,
    redact,
    write_result,
)
from pursue_index.tranche_autopilot.runner import CommandResult, Runner

__all__ = ["AutopilotConfig", "receipt_path", "refuse_without_checkout", "run_autopilot"]

_SHA = re.compile(r"[0-9a-f]{64}")
_PROTECTED_BRANCHES = frozenset({"main", "master"})
_RUN_ORDER = (rs.data_root_preflight, rs.scope_preview, rs.approve, rs.dry_run_scope,
              rs.storage_verify, rs.ocr_preflight, rs.promote, rs.ship_ready, rs.web_tests,
              rs.commit, rs.freshness_recheck)


@dataclass
class AutopilotConfig:
    tranche_sha: str
    result_path: Path
    repo_root: Path
    runner: Runner
    env: Mapping[str, str]
    behind: Callable[[Path], int] = commits_behind_on_poll_paths


def receipt_path(repo_root: Path, tranche_sha: str) -> Path:
    return repo_root / "data" / "tranche-diffs" / f"tranche-diff-{tranche_sha[:12]}.json"


def _stop(code: ExitCode, message: str, outcome: str | None = None) -> AutopilotStopError:
    return AutopilotStopError(code, message, outcome)


def _load_receipt(cfg: AutopilotConfig) -> dict[str, Any]:
    path = receipt_path(cfg.repo_root, cfg.tranche_sha)
    if not path.is_file():
        raise _stop(ExitCode.PRECONDITION, f"receipt missing: {path.name}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _stop(ExitCode.PRECONDITION, f"receipt unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise _stop(ExitCode.PRECONDITION, "receipt is not a JSON object")
    return doc


def _result_inside_checkout(cfg: AutopilotConfig) -> bool:
    return cfg.result_path.resolve().is_relative_to(cfg.repo_root.resolve())


def _check_checkout(cfg: AutopilotConfig) -> str:
    """The branch to commit on; refuses a dirty tree, detached HEAD or main."""
    if _result_inside_checkout(cfg):
        raise _stop(ExitCode.PRECONDITION, "--result must be outside the checkout")
    try:
        clean = is_clean(cfg.runner, cfg.repo_root)
    except GitError as exc:
        raise _stop(ExitCode.PRECONDITION, str(exc)) from exc
    if not clean:
        raise _stop(ExitCode.PRECONDITION, "working tree is not clean")
    branch = current_branch(cfg.runner, cfg.repo_root)
    if branch is None or branch in _PROTECTED_BRANCHES:
        raise _stop(ExitCode.PRECONDITION, "check out a release branch (not main, not detached)")
    return branch


def _freshness_baseline(cfg: AutopilotConfig) -> int:
    try:
        behind = cfg.behind(cfg.repo_root)
    except PollCheckError as exc:
        raise _stop(ExitCode.PRECONDITION, f"poll freshness unknown: {exc}") from exc
    if behind:
        raise _stop(ExitCode.INELIGIBLE, f"superseded: checkout is {behind} poll commit(s) "
                    "behind origin/main", Outcome.SUPERSEDED)
    return behind


def _assess(cfg: AutopilotConfig, receipt: dict[str, Any]) -> Eligibility:
    try:
        return assess(receipt, cfg.tranche_sha)
    except ReceiptError as exc:
        raise _stop(ExitCode.PRECONDITION, f"receipt not usable: {exc}") from exc


def _eligibility_doc(e: Eligibility | None) -> dict[str, Any]:
    if e is None:
        return {"verdict": "unknown", "reasons": [], "fields_changed": [], "summary": {},
                "field_change_cards": 0}
    return {"verdict": e.verdict, "reasons": e.reasons, "fields_changed": e.fields_changed,
            "summary": e.summary, "field_change_cards": e.field_change_cards}


class _Run:
    """Mutable state of one run, folded into the result document at the end."""

    def __init__(self, cfg: AutopilotConfig) -> None:
        self.cfg = cfg
        self.started_at = now_iso()
        self.steps = {name: Step(name) for name in rs.STEP_NAMES}
        self.branch: str | None = None
        self.eligibility: Eligibility | None = None
        self.ctx: rs.Context | None = None

    def execute(self) -> None:
        cfg = self.cfg
        if not _SHA.fullmatch(cfg.tranche_sha):
            raise _stop(ExitCode.PRECONDITION, "--tranche must match ^[0-9a-f]{64}$")
        self.branch = _check_checkout(cfg)
        baseline = _freshness_baseline(cfg)
        receipt = _load_receipt(cfg)
        self.eligibility = _assess(cfg, receipt)
        if self.eligibility.code is not None:
            raise _stop(self.eligibility.code, "; ".join(self.eligibility.reasons))
        # Children resolve the data paths against the checkout being promoted,
        # not whichever checkout the package was imported from.
        env = {**cfg.env, "PURSUE_REPO_ROOT": str(cfg.repo_root)}
        self.ctx = rs.Context(cfg.tranche_sha, cfg.repo_root, cfg.runner, env, cfg.behind,
                             self.eligibility, self.steps, receipt, behind_baseline=baseline)
        for step_fn in _RUN_ORDER:
            step_fn(self.ctx)

    def document(self, code: ExitCode, outcome: str, message: str) -> dict[str, Any]:
        cfg, ctx = self.cfg, self.ctx
        valid_sha = bool(_SHA.fullmatch(cfg.tranche_sha))
        failed = next((s.name for s in self.steps.values() if s.status == "failed"), None)
        done = code is ExitCode.DONE and self.branch is not None
        return {
            "schema_version": SCHEMA_VERSION,
            "tranche_sha": cfg.tranche_sha if valid_sha else None,
            "exit_code": int(code),
            "outcome": outcome,
            "message": message,
            "started_at": self.started_at,
            "finished_at": now_iso(),
            "repo_root": str(cfg.repo_root),
            "branch": self.branch,
            "eligibility": _eligibility_doc(self.eligibility),
            "steps": [s.as_dict() for s in self.steps.values()],
            "failed_step": failed,
            "promote_commits": list(ctx.commits) if ctx else [],
            "changed_paths": (ctx.changed if ctx and ctx.changed else
                              {"count": 0, "by_top_dir": {}, "paths": [], "truncated": False}),
            "operator_next": (operator_next(cfg.repo_root, self.branch, cfg.tranche_sha)
                              if done else []),
        }


def run_autopilot(cfg: AutopilotConfig) -> int:
    """Run the autopilot once; writes ``cfg.result_path`` and returns the exit code."""
    run = _Run(cfg)
    try:
        run.execute()
        code, outcome, message = ExitCode.DONE, Outcome.DONE, (
            "promoted and committed locally; publish with operator_next")
    except AutopilotStopError as stop:
        code, outcome, message = stop.code, stop.outcome, stop.message
    except Exception as exc:  # the result file and a documented code, always
        running = next((s for s in run.steps.values() if s.running), None)
        if running is not None:
            running.finish("failed", f"internal error: {type(exc).__name__}")
        code, outcome = ExitCode.GATE_FAILED, Outcome.GATE_FAILED
        message = redact(f"internal error: {type(exc).__name__}: {exc}")
    if _result_inside_checkout(cfg):  # refused above; never dirty the checkout
        return int(code)
    write_result(cfg.result_path, run.document(code, outcome, message))
    return int(code)


def _no_runner(*_args: object, **_kwargs: object) -> CommandResult:
    raise AssertionError("no command runs without a checkout")


def refuse_without_checkout(tranche_sha: str, result_path: Path, message: str) -> int:
    """Write a precondition-missing result when no checkout could be resolved."""
    cfg = AutopilotConfig(tranche_sha, result_path, Path.cwd(), _no_runner, {})
    target = result_path.resolve()
    if any((d / ".git").exists() for d in target.parents):  # never dirty a checkout
        return int(ExitCode.PRECONDITION)
    write_result(result_path, _Run(cfg).document(ExitCode.PRECONDITION, Outcome.PRECONDITION,
                                                 message))
    return int(ExitCode.PRECONDITION)
