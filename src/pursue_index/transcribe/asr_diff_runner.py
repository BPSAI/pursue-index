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

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pursue_index import get_logger
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff import (
    AGREEMENT_THRESHOLD,
    DisagreeingSpan,
    align_transcripts,
    classify_agreement,
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
class RowAsrDiffReport:
    """One row's outcome: a fresh comparison or an idempotency hit."""

    card_id: str
    row_key: str
    status: str  # "judged" | "review"
    agreement: float
    cost_usd: float
    disagreeing_spans: list[DisagreeingSpan]


def estimate_cost_usd(audio_duration_s: float, rate_usd_per_minute: float) -> float:
    """Projected spend for one second-engine pass over ``audio_duration_s``."""
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
    budget_usd: float,
    threshold: float = AGREEMENT_THRESHOLD,
) -> RowAsrDiffReport:
    """Diff one row against a second engine; write its sidecar row.

    Idempotent on ``(engine_a, engine_b)`` -- a row already compared under
    the same pair is returned from the sidecar with ``cost_usd=0.0`` and
    ``second_engine_fn`` is never called. Otherwise the projected cost is
    checked against ``budget_usd`` BEFORE the call, so a run never spends
    past its cap.
    """
    existing = sidecar.load_existing(sidecar_path).get(row_key)
    if existing and sidecar.should_skip(existing, engine_a=engine_a, engine_b=engine_b):
        return _from_existing(card_id, row_key, existing)

    projected = estimate_cost_usd(audio_duration_s, rate_usd_per_minute)
    if projected > budget_usd:
        raise AsrDiffBudgetExceededError(
            f"estimated ${projected:.2f} exceeds cap ${budget_usd:.2f} "
            f"before diffing {card_id} row {row_key!r}",
            partial_cost_usd=0.0,
        )

    text_b = second_engine_fn(audio_path)
    result = align_transcripts(text_a, text_b)
    status = classify_agreement(result.agreement, threshold)
    row = sidecar.build_row(
        row_key=row_key, engine_a=engine_a, engine_b=engine_b,
        result=result, threshold=threshold, status=status,
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
