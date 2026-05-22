"""Per-card QC runner: iterate cleaned-but-not-judged pages, write
verdicts to the QC sidecar, respect a USD budget cap.

Pure orchestration. The judge call is injected as ``grade_fn`` for
tests; production wires ``judge.grade_page``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pursue_index import get_logger
from pursue_index.clean.qc import judge as judge_mod
from pursue_index.clean.qc import sidecar as qc_sidecar
from pursue_index.clean.qc.prompt import judge_prompt_sha256

log = get_logger(__name__)

# Sonnet 4.6 pricing per Anthropic (2026-05-21): $3 / MTok input,
# $15 / MTok output. Cache-read at 1/10th input.
_RATE_INPUT_PER_M = 3.0
_RATE_OUTPUT_PER_M = 15.0
_RATE_CACHE_READ_PER_M = 0.30


class QcBudgetExceededError(RuntimeError):
    """Raised when the cumulative QC cost crosses the configured cap."""

    def __init__(
        self, message: str, *, partial_cost_usd: float = 0.0,
        card_id: str = "", pages_graded: int = 0,
    ) -> None:
        super().__init__(message)
        self.partial_cost_usd = partial_cost_usd
        self.card_id = card_id
        self.pages_graded = pages_graded


@dataclass
class CardQcReport:
    """Per-card outcome of a QC run."""
    card_id: str
    pages_graded: int
    pages_skipped: int          # already-graded, idempotency hit
    pages_skipped_judge: int    # judge declined (content filter, parse failure)
    cost_usd: float
    input_tokens: int
    output_tokens: int


def _estimate_cost(usage: dict[str, int]) -> float:
    return (
        usage["input_tokens"] / 1_000_000 * _RATE_INPUT_PER_M
        + usage["output_tokens"] / 1_000_000 * _RATE_OUTPUT_PER_M
        + usage["cache_read_tokens"] / 1_000_000 * _RATE_CACHE_READ_PER_M
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def _build_raw_by_page(rows: list[dict[str, Any]]) -> dict[int, str]:
    return {int(r["page"]): r.get("text", "") for r in rows if "page" in r}


def _process_page(
    *, card_id: str, page: int, raw_text: str, cleaned_row: dict[str, Any],
    judge_model_id: str, judge_prompt_sha: str, qc_path: Path,
    grade_fn: Callable[..., judge_mod.GradeResult],
) -> tuple[int, int, dict[str, int]]:
    """Grade one page; write the QC row; return (graded_delta,
    skipped_judge_delta, usage_dict)."""
    cleaned_text = cleaned_row.get("text_cleaned", "")
    result = grade_fn(
        raw_text=raw_text, cleaned_text=cleaned_text,
        model_id=judge_model_id,
    )
    row = judge_mod.build_row(
        card_id=card_id, page=page,
        raw_sha256=cleaned_row.get("input_sha256", ""),
        cleaned_sha256=cleaned_row.get("output_sha256", ""),
        judge_model_id=judge_model_id,
        judge_prompt_sha256=judge_prompt_sha,
        checks=result.checks,
        judge_skipped=result.judge_skipped,
    )
    qc_sidecar.write_row(qc_path, row)
    skipped_judge = 1 if result.judge_skipped is not None else 0
    graded = 0 if skipped_judge else 1
    return graded, skipped_judge, result.usage


@dataclass
class _LoopState:
    pages_graded: int = 0
    pages_skipped: int = 0
    pages_skipped_judge: int = 0


def _step_one_row(
    *, cleaned_row: dict[str, Any], state: _LoopState, totals: dict[str, int],
    existing_qc: dict[int, dict[str, Any]], raw_by_page: dict[int, str],
    judge_model_id: str, judge_prompt_sha: str, card_id: str,
    qc_path: Path, budget_usd: float,
    grade_fn: Callable[..., judge_mod.GradeResult],
) -> None:
    """Process one cleaned-row: idempotency check, budget gate, grade, accumulate.
    Raises QcBudgetExceededError when the cap would be crossed."""
    page = int(cleaned_row.get("page", 0))
    raw_sha = cleaned_row.get("input_sha256", "")
    cleaned_sha = cleaned_row.get("output_sha256", "")
    existing = existing_qc.get(page, {})
    if existing and qc_sidecar.should_skip_qc(
        existing, raw_sha256=raw_sha, cleaned_sha256=cleaned_sha,
        judge_model_id=judge_model_id, judge_prompt_sha256=judge_prompt_sha,
    ):
        state.pages_skipped += 1
        return
    current_cost = _estimate_cost(totals)
    if current_cost > budget_usd:
        raise QcBudgetExceededError(
            f"estimated ${current_cost:.2f} exceeds cap ${budget_usd:.2f}"
            f" before grading {card_id} page {page}",
            partial_cost_usd=current_cost, card_id=card_id,
            pages_graded=state.pages_graded,
        )
    graded_delta, skipped_judge_delta, usage = _process_page(
        card_id=card_id, page=page, raw_text=raw_by_page.get(page, ""),
        cleaned_row=cleaned_row, judge_model_id=judge_model_id,
        judge_prompt_sha=judge_prompt_sha, qc_path=qc_path, grade_fn=grade_fn,
    )
    state.pages_graded += graded_delta
    state.pages_skipped_judge += skipped_judge_delta
    for k, v in usage.items():
        totals[k] = totals.get(k, 0) + v


def run_card(
    *,
    card_id: str,
    raw_path: Path,
    cleaned_path: Path,
    qc_path: Path,
    judge_model_id: str,
    budget_usd: float,
    judge_prompt_sha: str | None = None,
    grade_fn: Callable[..., judge_mod.GradeResult] | None = None,
) -> CardQcReport:
    """Grade every cleaned page not yet in the QC sidecar.

    ``grade_fn`` defaults to ``judge.grade_page``; tests inject a fake.
    Budget cap is checked BEFORE each call (post-call cost crosses cap
    → next page raises rather than spending again).
    """
    if grade_fn is None:
        grade_fn = judge_mod.grade_page
    if judge_prompt_sha is None:
        judge_prompt_sha = judge_prompt_sha256()

    raw_by_page = _build_raw_by_page(_load_jsonl(raw_path))
    cleaned_rows = _load_jsonl(cleaned_path)
    existing_qc = qc_sidecar.load_existing(qc_path)

    state = _LoopState()
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_creation_tokens": 0}
    for cleaned_row in cleaned_rows:
        _step_one_row(
            cleaned_row=cleaned_row, state=state, totals=totals,
            existing_qc=existing_qc, raw_by_page=raw_by_page,
            judge_model_id=judge_model_id, judge_prompt_sha=judge_prompt_sha,
            card_id=card_id, qc_path=qc_path, budget_usd=budget_usd,
            grade_fn=grade_fn,
        )
    return CardQcReport(
        card_id=card_id,
        pages_graded=state.pages_graded,
        pages_skipped=state.pages_skipped,
        pages_skipped_judge=state.pages_skipped_judge,
        cost_usd=_estimate_cost(totals),
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
    )
