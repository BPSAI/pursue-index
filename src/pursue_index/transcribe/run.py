"""Run orchestration + coverage gate for the transcribe stage.

``preflight_coverage`` compares eligible-vs-produced with zero spend — the
verify-before-spend gate the CLI runs by default. ``run_transcribe``
produces (or skips already-produced) sidecars for eligible items using
injected ``transcribe_fn``/``probe_fn`` seams, so tests drive it without any
live AAI call, ffprobe binary, or audio file. The coverage contract is
``produced ⊇ eligible(scope)``; the report exposes the shortfall the CLI
turns into a non-zero exit. Per-item failures are skip-and-count: one bad
card never aborts the run.

Coverage is counted per ``(card_id, row_key)`` — the eligible *row*, not the
card. A card_id can be backed by more than one AUD row, and one row's
transcript never stands in for another's. The shortfall is a list rather than
a set difference so the report always names as many outstanding units as there
are outstanding rows.

A transcript that carries no utterances is its own outcome: the call returned,
but the row has no content, so it is recorded as empty and stays outstanding
rather than counting toward coverage.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pursue_index import get_logger
from pursue_index.transcribe.client import TranscriptResult
from pursue_index.transcribe.eligibility import (
    CoverageKey,
    EligibleItem,
    audio_path_for,
)
from pursue_index.transcribe.pages import write_transcript_sidecar

log = get_logger(__name__)

TranscribeFn = Callable[..., TranscriptResult]
ProbeFn = Callable[[Path], bool]


@dataclass
class TranscribeRunReport:
    """Eligible-vs-produced coverage for a transcribe run, plus its outcomes."""

    eligible: list[CoverageKey]
    produced: list[CoverageKey] = field(default_factory=list)
    failed: list[tuple[CoverageKey, str]] = field(default_factory=list)
    empty: list[CoverageKey] = field(default_factory=list)

    @property
    def missing(self) -> list[CoverageKey]:
        """Eligible rows with no transcript content (the shortfall)."""
        done = set(self.produced)
        return [key for key in self.eligible if key not in done]

    @property
    def ok(self) -> bool:
        """True iff ``produced ⊇ eligible`` — the coverage gate passes."""
        return not self.missing


def _covered_rows(meta: dict[str, object], card_id: str) -> set[CoverageKey]:
    """The ``(card_id, row_key)`` units one card's meta reports as carrying text.

    A row entry counts only when it contributed pages. A meta with no ``rows``
    block describes a card written as a single row, so an ``ok`` status there
    covers that card's one row.
    """
    rows = meta.get("rows")
    if isinstance(rows, list):
        return {
            (card_id, str(r.get("row_key", "") or ""))
            for r in rows
            if isinstance(r, dict) and int(r.get("pages", 0) or 0) > 0
        }
    return {(card_id, "")} if meta.get("status") == "ok" else set()


def produced_rows(out_dir: Path, card_ids: set[str]) -> set[CoverageKey]:
    """Every eligible ``(card_id, row_key)`` already carrying transcript text."""
    produced: set[CoverageKey] = set()
    for card_id in card_ids:
        meta_path = out_dir / card_id / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(meta, dict):
            produced |= _covered_rows(meta, card_id)
    return produced


def preflight_coverage(items: list[EligibleItem], out_dir: Path) -> TranscribeRunReport:
    """Report eligible-vs-produced without spending anything."""
    eligible = [i.coverage_key for i in items]
    produced = produced_rows(out_dir, {i.card_id for i in items})
    return TranscribeRunReport(
        eligible=eligible, produced=[k for k in eligible if k in produced]
    )


def _transcribe_one(
    item: EligibleItem,
    audio_dir: Path,
    out_dir: Path,
    *,
    transcribe_fn: TranscribeFn,
    probe_fn: ProbeFn,
) -> tuple[str | None, bool]:
    """Produce one row's transcript.

    Returns ``(error, produced_pages)``: ``error`` is a stated reason on
    failure and ``None`` otherwise, and ``produced_pages`` says whether the
    transcript carried any content. Never raises — all failure modes are
    captured so one row never aborts the run.
    """
    path = audio_path_for(item, audio_dir)
    if not path.exists():
        return f"audio file not found: {path}", False
    try:
        multichannel = probe_fn(path)
        result = transcribe_fn(path, multichannel=multichannel)
    except Exception as exc:  # per-item skip-and-count, never abort the run
        log.warning(
            "transcribe.item.failed",
            card_id=item.card_id, row_key=item.row_key, error=str(exc),
        )
        return str(exc), False
    pages = write_transcript_sidecar(
        item.card_id, out_dir, result.utterances,
        row_key=item.row_key,
        multichannel=result.multichannel,
        audio_duration_s=result.audio_duration_s,
        speakers=result.speakers,
        source=path.name,
    )
    log.info(
        "transcribe.row.written",
        card_id=item.card_id, row_key=item.row_key, pages=pages,
    )
    return None, pages > 0


def run_transcribe(
    items: list[EligibleItem],
    audio_dir: Path,
    out_dir: Path,
    *,
    transcribe_fn: TranscribeFn,
    probe_fn: ProbeFn,
) -> TranscribeRunReport:
    """Produce transcripts for eligible ``items``, then report coverage.

    Idempotent: a row already carrying transcript text is skipped (no AAI
    call). Failures and empty transcripts are per-row outcomes — neither
    aborts the rest, and both leave their row outstanding in
    ``report.missing``/``report.ok`` for a non-zero CLI exit.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = produced_rows(out_dir, {i.card_id for i in items})
    failed: list[tuple[CoverageKey, str]] = []
    empty: list[CoverageKey] = []
    for item in items:
        if item.coverage_key in produced:
            continue
        error, has_pages = _transcribe_one(
            item, audio_dir, out_dir, transcribe_fn=transcribe_fn, probe_fn=probe_fn
        )
        if error is not None:
            failed.append((item.coverage_key, error))
        elif not has_pages:
            empty.append(item.coverage_key)

    report = preflight_coverage(items, out_dir)
    report.failed = failed
    report.empty = empty
    return report
