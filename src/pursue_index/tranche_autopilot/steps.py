"""The autopilot's release steps, in runbook order.

Each function takes the run :class:`Context`, records its own :class:`Step`
and raises :class:`AutopilotStopError` to end the run. The order is
``STEP_NAMES`` (``engine._RUN_ORDER`` runs them). Two checks run ahead of the
first state change: the data-root preflight, and an in-process preview of the
dry run's scope -- so an approval is only ever recorded for a tranche already
shown to scope no content work. The dry run itself (which requires approval)
then re-proves it.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pursue_index.poll_freshness import PollCheckError
from pursue_index.tranche_autopilot.eligibility import Eligibility
from pursue_index.tranche_autopilot.gitops import (
    GitError,
    changed_paths,
    commit_paths,
    path_summary,
)
from pursue_index.tranche_autopilot.outcome import AutopilotStopError, ExitCode, Outcome
from pursue_index.tranche_autopilot.result import Step, commit_message, redact
from pursue_index.tranche_autopilot.runner import PURSUE, CommandResult, Runner
from pursue_index.tranche_autopilot.worklists import (
    WorklistCheck,
    WorklistError,
    check_worklists,
    preview_scope,
)

STEP_NAMES: tuple[str, ...] = (
    "data-root-preflight", "scope-preview", "approve", "dry-run-scope", "storage-verify",
    "ocr-preflight", "promote", "ship-ready", "web-tests", "commit", "freshness-recheck",
)
# A promote of a metadata-only tranche rewrites the manifest and its derived
# payloads; anything changed outside these top-level directories is refused.
COMMITTABLE_TOP_DIRS = frozenset({"data", "web"})
_DETAIL_CHARS = 600


@dataclass
class Context:
    tranche_sha: str
    repo_root: Path
    runner: Runner
    env: Mapping[str, str]
    behind: Callable[[Path], int]
    eligibility: Eligibility
    steps: dict[str, Step]
    receipt: dict[str, Any]
    behind_baseline: int = 0
    commits: list[str] = field(default_factory=list)
    changed: dict[str, Any] | None = None


def _tail(result: CommandResult) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return redact(text[-_DETAIL_CHARS:])


def _refuse_content_work(step: Step, lists: WorklistCheck, what: str) -> None:
    step.detail = (f"{what}: {len(lists.pdf_ids)} PDF/IMG, {len(lists.av_ids)} A/V; "
                   f"{lists.note}")
    if not lists.empty:
        step.status = "failed"
        raise AutopilotStopError(ExitCode.NEEDS_LEASE,
                                 f"{what} scoped content work; run the attended release")


def _run(ctx: Context, step: Step, argv: Sequence[str], timeout: float,
         cwd: Path | None = None) -> CommandResult:
    step.command = shlex.join(argv)
    step.start()
    result = ctx.runner(argv, cwd=cwd or ctx.repo_root, timeout=timeout, env=ctx.env)
    if result.returncode != 0:
        step.finish("failed", _tail(result), result.returncode)
        raise AutopilotStopError(ExitCode.GATE_FAILED,
                            f"step {step.name} failed (exit {result.returncode})")
    step.finish("ok", _tail(result), 0)
    return result


def approve(ctx: Context) -> None:
    step = ctx.steps["approve"]
    check = [PURSUE, "ingest", "check", "--tranche", ctx.tranche_sha]
    step.command = shlex.join(check)
    step.start()
    probe = ctx.runner(check, cwd=ctx.repo_root, timeout=120, env=ctx.env)
    if probe.returncode == 0:
        step.finish("skipped", "already approved", 0)
        return
    if probe.returncode != 1:
        step.finish("failed", _tail(probe), probe.returncode)
        raise AutopilotStopError(ExitCode.GATE_FAILED, "step approve failed: ingest check errored")
    fields = ", ".join(ctx.eligibility.fields_changed) or "none"
    note = (f"autopilot: metadata-only tranche {ctx.tranche_sha[:12]}; receipt shows only "
            f"allowlisted field edits ({fields})")
    _run(ctx, step, [PURSUE, "ingest", "approve", "--tranche", ctx.tranche_sha,
                     "--note", note], timeout=900)


def dry_run_scope(ctx: Context) -> None:
    step = ctx.steps["dry-run-scope"]
    _run(ctx, step, [PURSUE, "ingest", "run", "--tranche", ctx.tranche_sha,
                     "--from-diff", "--dry-run"], timeout=900)
    try:
        lists = check_worklists(ctx.repo_root, ctx.tranche_sha)
    except WorklistError as exc:
        step.finish("failed", str(exc), step.exit_code)
        raise AutopilotStopError(ExitCode.GATE_FAILED, f"step dry-run-scope failed: {exc}") from exc
    _refuse_content_work(step, lists, "dry run")


def storage_verify(ctx: Context) -> None:
    _run(ctx, ctx.steps["storage-verify"], [PURSUE, "storage", "verify"], timeout=300)


def ocr_preflight(ctx: Context) -> None:
    # Only a non-empty work-list spends on OCR, and dry_run_scope has
    # already refused those, so the preflight has nothing to guard.
    step = ctx.steps["ocr-preflight"]
    step.finish("skipped", "work-lists empty; no OCR to preflight")


def scope_preview(ctx: Context) -> None:
    step = ctx.steps["scope-preview"]
    step.command = "(in-process) ingest_scope.scope_worklist + summarize_ingest_work"
    step.start()
    root = data_root(ctx)
    assert root is not None  # data_root_preflight ran first
    lists = preview_scope(ctx.repo_root, ctx.receipt, ctx.tranche_sha, root)
    step.finish("ok")
    _refuse_content_work(step, lists, "scope preview")


def data_root(ctx: Context) -> Path | None:
    """``PURSUE_DATA_ROOT`` from the child environment, relative to the checkout."""
    raw = ctx.env.get("PURSUE_DATA_ROOT", "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ctx.repo_root / path


def data_root_preflight(ctx: Context) -> None:
    # Explicit env only (not a .env fallback): the scheduler exports it, and a
    # silent default of ./data must never stand in for the real data root.
    step = ctx.steps["data-root-preflight"]
    step.start()
    root = data_root(ctx)
    if root is None or not root.is_dir():
        step.finish("failed", "PURSUE_DATA_ROOT is unset or not a directory")
        raise AutopilotStopError(ExitCode.PRECONDITION,
                                 "PURSUE_DATA_ROOT is unset or not a directory")
    step.finish("ok", "PURSUE_DATA_ROOT is a directory")


def promote(ctx: Context) -> None:
    _run(ctx, ctx.steps["promote"],
         [PURSUE, "ingest", "run", "--tranche", ctx.tranche_sha], timeout=3600)


def ship_ready(ctx: Context) -> None:
    _run(ctx, ctx.steps["ship-ready"], ["make", "ship-ready"], timeout=4 * 3600)


def web_tests(ctx: Context) -> None:
    _run(ctx, ctx.steps["web-tests"], ["npm", "run", "test"], timeout=3600,
         cwd=ctx.repo_root / "web")


def commit(ctx: Context) -> None:
    step = ctx.steps["commit"]
    step.command = "git add --all -- <changed paths> && git commit"
    step.start()
    try:
        paths = changed_paths(ctx.runner, ctx.repo_root)
        if not paths:
            raise GitError("promote and ship-ready left no changes to commit")
        stray = [p for p in paths if p.split("/", 1)[0] not in COMMITTABLE_TOP_DIRS]
        if stray:
            raise GitError(f"refusing to commit paths outside {sorted(COMMITTABLE_TOP_DIRS)}: "
                           f"{', '.join(stray[:10])}")
        message = commit_message(ctx.tranche_sha, ctx.eligibility.summary,
                                 ctx.eligibility.fields_changed)
        ctx.commits.append(commit_paths(ctx.runner, ctx.repo_root, paths, message))
    except GitError as exc:
        step.finish("failed", str(exc))
        raise AutopilotStopError(ExitCode.GATE_FAILED, f"step commit failed: {exc}") from exc
    ctx.changed = path_summary(paths)
    step.finish("ok", f"committed {len(paths)} path(s) as {ctx.commits[-1][:12]}", 0)


def freshness_recheck(ctx: Context) -> None:
    step = ctx.steps["freshness-recheck"]
    step.start()
    try:
        now = ctx.behind(ctx.repo_root)
    except PollCheckError as exc:
        step.finish("failed", str(exc))
        raise AutopilotStopError(ExitCode.GATE_FAILED, f"step freshness-recheck failed: {exc}") from exc
    if now != ctx.behind_baseline:
        step.finish("failed", f"origin/main gained {now} poll commit(s) during the run")
        raise AutopilotStopError(
            ExitCode.INELIGIBLE,
            f"superseded: the poller moved origin/main during the run; the local commit "
            f"{ctx.commits[-1][:12] if ctx.commits else ''} is stale -- do not publish it",
            Outcome.SUPERSEDED)
    step.finish("ok", "origin/main unchanged on poll-written paths")
