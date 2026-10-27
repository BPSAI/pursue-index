"""Per-row second-engine ASR diff: orchestration + budget + idempotency.

Mirrors ``clean.qc.runner``'s shape -- budget checked BEFORE the engine
call, the engine call itself injected as ``second_engine_fn`` so tests
drive this with two fakes standing in for "two ASR engines", never a live
vendor. Cost is duration-based (no token usage to meter, unlike the
page-judge pass): ``estimate_cost_usd`` is what a CLI's ``--dry-run`` sums
over every eligible row before any real spend -- the operator-attended
gate the task requires.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from pursue_index import get_logger
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff import (
    AGREEMENT_THRESHOLD,
    DisagreeingSpan,
    align_transcripts,
    classify_result,
)

log = get_logger(__name__)

#: Audio path -> engine B's transcript text. Production wiring (which
#: vendor, which credentials) is the operator's call and is made at the
#: call site, not here.
SecondEngineFn = Callable[[Path], str]


class AsrDiffBudgetExceededError(RuntimeError):
    """Raised when running a row would cross the configured USD cap."""

    def __init__(self, message: str, *, partial_cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.partial_cost_usd = partial_cost_usd


@dataclass
class AsrDiffBudget:
    """One USD cap shared by every row of a bulk pass; ``run_row`` charges it."""

    cap_usd: float
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.cap_usd) or self.cap_usd < 0:
            raise ValueError(f"budget cap must be a finite, non-negative USD amount, got {self.cap_usd!r}")

    def can_afford(self, cost_usd: float) -> bool:
        return self.spent_usd + cost_usd <= self.cap_usd

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd


@dataclass
class RowAsrDiffReport:
    """One row's outcome: a fresh comparison or an idempotency hit."""

    card_id: str
    row_key: str
    status: str  # "judged" | "review"
    agreement: float
    cost_usd: float
    disagreeing_spans: list[DisagreeingSpan]


def estimate_cost_usd(audio_duration_s: float, rate_usd_per_minute: float) -> float:
    """Projected spend for one second-engine pass over ``audio_duration_s``.

    Raises ``ValueError`` for a negative or non-finite duration or rate: a
    negative projection would pass the budget gate and then refund the cap.
    """
    for label, value in (("duration", audio_duration_s), ("rate", rate_usd_per_minute)):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"audio {label} must be finite and non-negative, got {value!r}")
    return (audio_duration_s / 60.0) * rate_usd_per_minute


def _from_existing(card_id: str, row_key: str, existing: dict) -> RowAsrDiffReport:
    """An idempotency hit: report the prior comparison, spend nothing."""
    return RowAsrDiffReport(
        card_id=card_id, row_key=row_key, status=existing["status"],
        agreement=existing["agreement"], cost_usd=0.0,
        disagreeing_spans=[
            DisagreeingSpan(
                a_text=s["a_text"], b_text=s["b_text"],
                a_range=tuple(s["a_range"]), b_range=tuple(s["b_range"]),
            )
            for s in existing.get("disagreeing_spans", [])
        ],
    )


def run_row(
    *,
    card_id: str,
    row_key: str,
    engine_a: str,
    engine_b: str,
    text_a: str,
    audio_path: Path,
    sidecar_path: Path,
    second_engine_fn: SecondEngineFn,
    audio_duration_s: float,
    rate_usd_per_minute: float,
    budget: AsrDiffBudget,
    threshold: float = AGREEMENT_THRESHOLD,
) -> RowAsrDiffReport:
    """Diff one row against a second engine; write its sidecar row.

    Idempotent on ``(engine_a, engine_b, sha256(text_a), transcript version)`` -- a row already
    compared under the same pair and transcript is returned from the
    sidecar with ``cost_usd=0.0`` and ``second_engine_fn`` is never called. Otherwise the projected cost is
    checked against the shared ``budget`` (spend so far plus this row) BEFORE
    the call, so a bulk run never spends past its cap.
    """
    text_sha = sidecar.text_sha256(text_a)
    version = sidecar.transcript_version(sidecar_path.parent)
    existing = sidecar.load_existing(sidecar_path).get(row_key)
    if existing and sidecar.should_skip(
        existing, engine_a=engine_a, engine_b=engine_b,
        text_a_sha256=text_sha, transcript_version=version,
    ):
        return _from_existing(card_id, row_key, existing)

    projected = estimate_cost_usd(audio_duration_s, rate_usd_per_minute)
    if not budget.can_afford(projected):
        raise AsrDiffBudgetExceededError(
            f"estimated ${projected:.2f} on top of ${budget.spent_usd:.2f} spent "
            f"exceeds cap ${budget.cap_usd:.2f} before diffing {card_id} row {row_key!r}",
            partial_cost_usd=budget.spent_usd,
        )

    # Charged before the call: a vendor bills the attempt, so a call that
    # raises still counts against the cap.
    budget.charge(projected)
    text_b = second_engine_fn(audio_path)
    result = align_transcripts(text_a, text_b)
    status = classify_result(result, threshold)
    row = sidecar.build_row(
        row_key=row_key, engine_a=engine_a, engine_b=engine_b,
        result=result, threshold=threshold, status=status,
        text_a_sha256=text_sha, transcript_version=version,
    )
    sidecar.write_row(sidecar_path, row)
    log.info(
        "asr_diff.row.written",
        card_id=card_id, row_key=row_key, status=status, agreement=result.agreement,
    )
    return RowAsrDiffReport(
        card_id=card_id, row_key=row_key, status=status, agreement=result.agreement,
        cost_usd=projected, disagreeing_spans=result.disagreeing_spans,
    )


def run_rows(
    calls: Iterable[Callable[[], RowAsrDiffReport]],
) -> tuple[list[RowAsrDiffReport], AsrDiffBudgetExceededError | None]:
    """Run per-row calls sharing one budget; stop at the first cap breach.

    Returns the reports completed so far and the breach (``None`` if the
    whole loop fit under the cap).
    """
    reports: list[RowAsrDiffReport] = []
    for call in calls:
        try:
            reports.append(call())
        except AsrDiffBudgetExceededError as exc:
            log.warning("asr_diff.budget.stop", spent_usd=exc.partial_cost_usd)
            return reports, exc
    return reports, None
