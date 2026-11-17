"""The live second-engine pass over AUD rows: plan, dry-run estimate, run.

``plan_rows`` walks the same rows as the ``asr-diff run`` preview and labels
each one ``pending`` (to compare), ``compared`` (a comparison under this
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
from pursue_index.transcribe.asr_diff_runner import (
    AsrDiffBudget,
    RowAsrDiffReport,
    SecondEngineFn,
    run_row,
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


def _duration(meta: dict, row: dict) -> float:
    value = row.get("audio_duration_s")
    if value is None and len(meta.get("rows") or []) <= 1:
        value = meta.get("audio_duration_s")  # older single-row meta keeps it top-level
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _card_rows(
    card_id: str, title: str, ocr_dir: Path, audio_dir: Path, engine_b: str,
    dvids_video_id: str | None, mirrored: dict[str, Path],
) -> list[LiveRow]:
    card_dir = ocr_dir / card_id
    meta = sidecar.read_meta(card_dir)
    if not meta or meta.get("status") != "ok":
        return [LiveRow(card_id, "", "skipped", 0.0, reason="no completed transcript")]
    rows = meta.get("rows") or [{"row_key": ""}]
    if len(rows) > 1:
        return [LiveRow(card_id, str(r.get("row_key", "") or ""), "skipped", _duration(meta, r),
                        reason="multi-row card: pages are not separable per row") for r in rows]
    row = rows[0]
    row_key = str(row.get("row_key", "") or "")
    engine_a = str(meta.get("engine", ""))
    prior = sidecar.load_existing(card_dir / sidecar.SIDECAR_FILE).get(row_key)
    current = prior and sidecar.should_skip(
        prior, engine_a=engine_a, engine_b=engine_b,
        transcript_version=sidecar.transcript_version(card_dir),
        pages_digest=sidecar.card_pages_digest(card_dir),
    )
    item = EligibleItem(card_id=card_id, title=title, dvids_video_id=dvids_video_id, row_key=row_key)
    audio = audio_path_for(item, audio_dir)
    if not audio.is_file() and card_id in mirrored:
        audio = mirrored[card_id]
    state = "compared" if current else "pending"
    return [LiveRow(card_id, row_key, state, _duration(meta, row), audio, engine_a)]


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
    reports: list[RowAsrDiffReport] = []
    for row in rows:
        if row.state != "pending":
            continue
        if row.audio_path is None or not row.audio_path.is_file():
            if on_row:
                on_row(row, None, "audio not staged")
            continue
        if expected_sha is not None:
            want = expected_sha.get(row.card_id)
            if want is None or file_sha256(row.audio_path) != want:
                if on_row:
                    on_row(row, None, "audio sha256 does not match the registry")
                continue
        card_dir = ocr_dir / row.card_id
        meta = sidecar.read_meta(card_dir) or {}
        report = run_row(
            card_id=row.card_id, row_key=row.row_key, engine_a=row.engine_a, engine_b=engine_b,
            text_a=transcript_text(card_dir, meta), audio_path=row.audio_path,
            sidecar_path=card_dir / sidecar.SIDECAR_FILE, second_engine_fn=engine,
            audio_duration_s=row.duration_s, rate_usd_per_minute=RATE_USD_PER_MINUTE,
            budget=budget,
        )
        reports.append(report)
        if on_row:
            on_row(row, report, "")
    return reports
