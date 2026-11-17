"""The live second-engine pass over AUD rows: plan, dry-run estimate, run.

``plan_rows`` walks the same rows as the ``asr-diff run`` preview, with the
same check (``asr_diff_rows.card_row_states``), and labels each one ``pending`` (to compare), ``compared`` (a comparison under this
engine pair already covers the current transcript) or ``skipped`` (with the
reason). ``run_pending`` hands each pending row to
``asr_diff_runner.run_row`` with the second engine supplied by the caller.

The second engine runs locally, so a row costs nothing: every row is run at
``rate_usd_per_minute=0`` against a $0 budget, which a $0 row always fits.
Runtime and VRAM in the dry run are estimates from a bake-off of this
engine on 60-second clips, not measurements of this run.

What the pass produces is disagreement flags between two engines. Neither
engine's text is treated as correct, and agreement is not an accuracy score.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff_rows import card_row_states
from pursue_index.transcribe.asr_diff_runner import (
    AsrDiffBudget,
    RowAsrDiffReport,
    SecondEngineFn,
    run_row,
    run_rows,
)
from pursue_index.transcribe.eligibility import EligibleItem, audio_path_for

#: Decode wall-clock per audio second, and model load time, from the bake-off.
EST_RTF = 0.0064
EST_LOAD_S = 40.0
#: Peak GPU memory observed for this engine on chunks up to 60 s.
EST_PEAK_VRAM_GIB = 2.3
RATE_USD_PER_MINUTE = 0.0


@dataclass(frozen=True)
class LiveRow:
    """One AUD row and what the live pass would do with it."""

    card_id: str
    row_key: str
    state: str  # "pending" | "compared" | "skipped"
    duration_s: float
    audio_path: Path | None = None
    engine_a: str = ""
    reason: str = ""


def _speaker_labels(meta: dict) -> set[str]:
    rows = meta.get("rows") or [meta]
    names = {str(s) for r in rows if isinstance(r, dict) for s in (r.get("speakers") or [])}
    return names | {f"Speaker {n}" for n in names}


def transcript_text(card_dir: Path, meta: dict) -> str:
    """Engine A's published text for the card: ``pages.jsonl`` in page order,
    with the speaker labels the transcript stage adds removed (a label is not
    a spoken word, and would otherwise read as a disagreement at every turn)."""
    rows = [json.loads(line) for line in (card_dir / "pages.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda r: int(r["page"]))
    labels = sorted(_speaker_labels(meta), key=len, reverse=True)
    label_re = re.compile(r"^(?:" + "|".join(map(re.escape, labels)) + r"):\s*") if labels else None
    lines = []
    for row in rows:
        for line in str(row.get("text") or "").splitlines():
            line = line.strip()
            if label_re:
                line = label_re.sub("", line)
            if line:
                lines.append(line)
    return " ".join(lines)


def mirror_audio(registry_path: Path, mirror_dir: Path) -> dict[str, Path]:
    """``{card_id: archived bytes}`` from the asset-bytes registry (last row
    wins), for cards whose ``r2-mirror`` copy exists at the registered size."""
    out: dict[str, Path] = {}
    if not registry_path.is_file():
        return out
    rows: dict[str, dict] = {}
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("card_id") and row.get("archive_key"):
            rows[str(row["card_id"])] = row
    for card_id, row in rows.items():
        path = mirror_dir / str(row["archive_key"])
        if not path.resolve().is_relative_to(mirror_dir.resolve()):
            continue
        if path.is_file() and path.stat().st_size == row.get("byte_size"):
            out[card_id] = path
    return out


def registry_shas(registry_path: Path) -> dict[str, str]:
    """``{card_id: byte_sha256}`` from the asset-bytes registry (last row wins)."""
    out: dict[str, str] = {}
    if not registry_path.is_file():
        return out
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("card_id") and isinstance(row.get("byte_sha256"), str):
            out[str(row["card_id"])] = row["byte_sha256"]
    return out


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _card_rows(
    card_id: str, title: str, ocr_dir: Path, audio_dir: Path, engine_b: str,
    dvids_video_id: str | None, mirrored: dict[str, Path],
) -> list[LiveRow]:
    states = card_row_states(ocr_dir / card_id, engine_b)
    if any(s.state == "skipped" for s in states):
        return [LiveRow(card_id, s.row_key, s.state, s.duration_s, reason=s.reason) for s in states]
    (row,) = states
    item = EligibleItem(card_id=card_id, title=title, dvids_video_id=dvids_video_id, row_key=row.row_key)
    audio = audio_path_for(item, audio_dir)
    if not audio.is_file() and card_id in mirrored:
        audio = mirrored[card_id]
    return [LiveRow(card_id, row.row_key, row.state, row.duration_s, audio, row.engine_a)]


def plan_rows(
    cards: list[tuple[str, str, str | None]], ocr_dir: Path, audio_dir: Path, engine_b: str,
    mirrored: dict[str, Path] | None = None,
) -> list[LiveRow]:
    """Every AUD row, labelled. ``cards`` is ``(card_id, title, dvids_video_id)``.

    A row's audio is the file staged in ``audio_dir`` (``audio_path_for``),
    else the card's archived bytes in ``mirrored`` (``mirror_audio``)."""
    out: list[LiveRow] = []
    for card_id, title, dvids in cards:
        out.extend(_card_rows(card_id, title, ocr_dir, audio_dir, engine_b, dvids, mirrored or {}))
    return out


def estimate(rows: list[LiveRow]) -> dict[str, float]:
    """Dry-run totals for the pending rows (runtime and VRAM are bake-off estimates)."""
    pending = [r for r in rows if r.state == "pending"]
    audio_s = sum(r.duration_s for r in pending)
    return {
        "pending": len(pending),
        "compared": sum(r.state == "compared" for r in rows),
        "skipped": sum(r.state == "skipped" for r in rows),
        "audio_min": audio_s / 60.0,
        "runtime_min": (EST_LOAD_S + audio_s * EST_RTF) / 60.0 if pending else 0.0,
        "peak_vram_gib": EST_PEAK_VRAM_GIB if pending else 0.0,
        "cost_usd": 0.0,
    }


def run_pending(
    rows: list[LiveRow], ocr_dir: Path, engine_b: str, engine: SecondEngineFn,
    on_row: Callable[[LiveRow, RowAsrDiffReport | None, str], None] | None = None,
    expected_sha: dict[str, str] | None = None,
) -> list[RowAsrDiffReport]:
    """Run ``engine`` over every pending row whose audio is staged.

    With ``expected_sha`` (the registry's ``byte_sha256`` per card), a row's
    audio is hashed first and only bytes matching the registry reach the
    engine: anything else -- including a substituted file, or one ffmpeg
    would follow as a playlist -- is skipped and reported.
    """
    budget = AsrDiffBudget(cap_usd=0.0)
    calls = [_row_call(row, ocr_dir, engine_b, engine, budget, on_row, expected_sha)
             for row in rows if row.state == "pending"]
    # run_rows is the runner's shared-budget loop: it stops at the first cap
    # breach. The local engine's $0 rate never breaches, but the loop is the same.
    done, stopped = run_rows(calls)
    if stopped is not None and on_row:
        on_row(rows[0], None, "stopped: budget cap reached")
    return [r for r in done if r is not None]


def _row_call(
    row: LiveRow, ocr_dir: Path, engine_b: str, engine: SecondEngineFn, budget: AsrDiffBudget,
    on_row: Callable[[LiveRow, RowAsrDiffReport | None, str], None] | None,
    expected_sha: dict[str, str] | None,
) -> Callable[[], RowAsrDiffReport | None]:
    """One row's call for ``run_rows``. The audio is checked inside the call, just
    before the engine reads it, so the check-to-read gap stays small. A row
    that fails a check is reported and yields ``None``."""
    def call() -> RowAsrDiffReport | None:
        if row.audio_path is None or not row.audio_path.is_file():
            return _skip(row, on_row, "audio not staged")
        if expected_sha is not None:
            want = expected_sha.get(row.card_id)
            if want is None or file_sha256(row.audio_path) != want:
                return _skip(row, on_row, "audio sha256 does not match the registry")
        card_dir = ocr_dir / row.card_id
        meta = sidecar.read_meta(card_dir) or {}
        report = run_row(
            card_id=row.card_id, row_key=row.row_key, engine_a=row.engine_a, engine_b=engine_b,
            text_a=transcript_text(card_dir, meta), audio_path=row.audio_path,
            sidecar_path=card_dir / sidecar.SIDECAR_FILE, second_engine_fn=engine,
            audio_duration_s=row.duration_s, rate_usd_per_minute=RATE_USD_PER_MINUTE,
            budget=budget,
        )
        if on_row:
            on_row(row, report, "")
        return report
    return call


def _skip(row: LiveRow, on_row: Callable | None, reason: str) -> None:
    if on_row:
        on_row(row, None, reason)
    return None
