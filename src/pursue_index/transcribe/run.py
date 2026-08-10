"""Run orchestration + coverage gate for the transcribe stage (pipeline
stage 8). Identical shape to ``vision.run`` (T48.4).

``preflight_coverage`` compares eligible-vs-produced with zero spend — the
verify-before-spend gate the CLI runs by default. ``run_transcribe``
produces (or skips already-produced) sidecars for eligible items using
injected ``transcribe_fn``/``probe_fn`` seams, so tests drive it without any
live AAI call, ffprobe binary, or audio file. The coverage contract is
``produced ⊇ eligible(worklist)``; the report exposes the shortfall the CLI
turns into a non-zero exit. Per-item failures are skip-and-count: one bad
card never aborts the run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pursue_index import get_logger
from pursue_index.transcribe.client import TranscriptResult
from pursue_index.transcribe.eligibility import EligibleItem, audio_path_for
from pursue_index.transcribe.pages import write_transcript_sidecar

log = get_logger(__name__)

TranscribeFn = Callable[..., TranscriptResult]
ProbeFn = Callable[[Path], bool]


@dataclass
class TranscribeRunReport:
    """Eligible-vs-produced coverage for a transcribe run, plus failures."""

    eligible: list[str]
    produced: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def missing(self) -> set[str]:
        """Eligible card_ids with no produced sidecar (the shortfall)."""
        return set(self.eligible) - set(self.produced)

    @property
    def ok(self) -> bool:
        """True iff ``produced ⊇ eligible`` — the coverage gate passes."""
        return not self.missing


def produced_card_ids(out_dir: Path, eligible_ids: set[str]) -> set[str]:
    """Eligible card_ids that already have an ``ok`` transcript sidecar."""
    produced: set[str] = set()
    for card_id in eligible_ids:
        meta_path = out_dir / card_id / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        if meta.get("status") == "ok":
            produced.add(card_id)
    return produced


def preflight_coverage(items: list[EligibleItem], out_dir: Path) -> TranscribeRunReport:
    """Report eligible-vs-produced without spending anything."""
    eligible = [i.card_id for i in items]
    produced = produced_card_ids(out_dir, set(eligible))
    return TranscribeRunReport(
        eligible=eligible, produced=[c for c in eligible if c in produced]
    )


def _transcribe_one(
    item: EligibleItem,
    audio_dir: Path,
    out_dir: Path,
    *,
    transcribe_fn: TranscribeFn,
    probe_fn: ProbeFn,
) -> tuple[str, str] | None:
    """Produce one card's sidecar. Returns ``(card_id, error)`` on failure,
    ``None`` on success. Never raises — all failure modes are captured."""
    path = audio_path_for(item, audio_dir)
    if not path.exists():
        return item.card_id, f"audio file not found: {path}"
    try:
        multichannel = probe_fn(path)
        result = transcribe_fn(path, multichannel=multichannel)
    except Exception as exc:  # per-item skip-and-count, never abort the run
        log.warning("transcribe.item.failed", card_id=item.card_id, error=str(exc))
        return item.card_id, str(exc)
    write_transcript_sidecar(
        item.card_id, out_dir, result.utterances,
        multichannel=result.multichannel,
        audio_duration_s=result.audio_duration_s,
        speakers=result.speakers,
        source=path.name,
    )
    log.info("transcribe.card.written", card_id=item.card_id)
    return None


def run_transcribe(
    items: list[EligibleItem],
    audio_dir: Path,
    out_dir: Path,
    *,
    transcribe_fn: TranscribeFn,
    probe_fn: ProbeFn,
) -> TranscribeRunReport:
    """Produce sidecars for eligible ``items``, then report coverage.

    Idempotent: a card already carrying an ``ok`` sidecar is skipped (no
    AAI call). Failures are per-item skip-and-count — one bad card never
    aborts the rest, but ``report.missing``/``report.ok`` surface the
    shortfall for a non-zero CLI exit.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    eligible_ids = {i.card_id for i in items}
    produced = produced_card_ids(out_dir, eligible_ids)
    failed: list[tuple[str, str]] = []
    for item in items:
        if item.card_id in produced:
            continue
        outcome = _transcribe_one(
            item, audio_dir, out_dir, transcribe_fn=transcribe_fn, probe_fn=probe_fn
        )
        if outcome is not None:
            failed.append(outcome)

    report = preflight_coverage(items, out_dir)
    report.failed = failed
    return report
