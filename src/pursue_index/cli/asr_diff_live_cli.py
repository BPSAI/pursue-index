"""``pursue transcribe asr-diff live`` -- the second-engine pass, local engine.

Without ``--confirm`` this is a dry run: it lists every AUD row as pending,
already compared or skipped, totals the pending audio, and estimates runtime
and GPU memory. It loads no model and writes nothing. With ``--confirm`` it
runs the local second engine (Parakeet TDT 0.6B v3 at a pinned revision,
``pursue_index.transcribe.engine_b_parakeet``) over the pending rows through
``asr_diff_runner.run_row``, writing one ``asr_diff.jsonl`` row per card.

The engine is local and open-weights, so the pass costs $0: rows run at a
$0/min rate against a $0 cap, which can never refuse a $0 row. It still
needs a GPU and the ``asr-b`` extra, and stays operator-attended: run it
yourself, under whatever resource limits the host needs.

The output is disagreement flags between two engines. It does not say
which engine is right, and agreement is not an accuracy score.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index.card_id import InvalidCardIdError
from pursue_index.cli import ingest_defaults
from pursue_index.cli.asr_diff_cli import _aud_card_ids
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.text_control import console_text
from pursue_index.transcribe import asr_diff_live as live
from pursue_index.transcribe.engine_b_parakeet import ENGINE_B_NAME, make_parakeet_engine

console = Console()

#: Builds the second engine; replaced in tests so no model is ever loaded.
engine_factory = make_parakeet_engine


def _cards(manifest: Path, cards: str | None) -> list[tuple[str, str, str | None]]:
    wanted = set(_aud_card_ids(manifest, cards))
    out, seen = [], set()
    for c in load_manifest(manifest).cards:
        if c.card_id in wanted and c.card_id not in seen:
            seen.add(c.card_id)
            out.append((c.card_id, c.title, c.dvids_video_id))
    return out


def _print_plan(rows: list[live.LiveRow]) -> None:
    table = Table(title="asr-diff live DRY-RUN -- no model loaded, nothing written")
    for col in ("Card", "Row", "Minutes", "State", "Audio"):
        table.add_column(col)
    for r in rows:
        staged = "-" if r.audio_path is None else (
            "missing" if not r.audio_path.is_file() else
            "mirror" if r.audio_path.is_relative_to(settings.r2_mirror_dir) else "staged")
        state = r.state if not r.reason else f"{r.state}: {r.reason}"
        table.add_row(console_text(r.card_id), console_text(r.row_key) or "-",
                      f"{r.duration_s / 60:.1f}", console_text(state), staged)
    console.print(table)
    e = live.estimate(rows)
    console.print(
        f"[yellow]DRY-RUN[/yellow]: {e['pending']:.0f} pending, {e['compared']:.0f} already compared, "
        f"{e['skipped']:.0f} skipped. Pending audio {e['audio_min']:.1f} min. "
        f"Engine B: [bold]{ENGINE_B_NAME}[/bold] (local). "
        f"Estimated runtime {e['runtime_min']:.1f} min, peak GPU memory about "
        f"{e['peak_vram_gib']:.1f} GiB (estimates from a bake-off on 60 s clips). "
        f"Cost $0.00: local engine, $0/min rate, $0 cap."
    )


def _report_row(row: live.LiveRow, report, problem: str) -> None:
    if report is None:
        console.print(f"[red]not run[/red] {console_text(row.card_id)}: {console_text(problem)}")
        return
    flags = len(report.disagreeing_spans)
    console.print(
        f"{console_text(row.card_id)} row {console_text(row.row_key) or '-'}: {report.status}, "
        f"agreement {report.agreement:.3f}, {flags} disagreement span(s) flagged"
    )


def asr_diff_live(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    out: Path | None = typer.Option(None, "--out", help="Transcript sidecar root (default: settings.ocr_dir)."),
    audio_dir: Path | None = typer.Option(
        None, "--audio-dir", help="Staged source audio, one file per row (default: <data root>/av-fetch). "
        "A row with nothing staged reads the card's archived bytes from the r2-mirror, per the registry.",
    ),
    registry: Path | None = typer.Option(
        None, "--registry", help="asset-bytes-registry.jsonl (default: this checkout's data/).",
    ),
    cards: str | None = typer.Option(None, "--cards", help="Comma-separated card_ids. Defaults to every AUD card."),
    device: str = typer.Option("cuda", "--device", help="Torch device for the second engine."),
    confirm: bool = typer.Option(False, "--confirm", help="Actually run the second engine. Without it: dry run only."),
) -> None:
    """Dry-run, or with --confirm run, the local second engine over pending AUD rows."""
    out_dir = out or settings.ocr_dir
    audio_root = audio_dir or (settings.data_root / "av-fetch")
    try:
        mirrored = live.mirror_audio(registry or ingest_defaults.DEFAULT_ASSET_REGISTRY,
                                     settings.r2_mirror_dir)
        rows = live.plan_rows(_cards(manifest, cards), out_dir, audio_root, ENGINE_B_NAME, mirrored)
    except InvalidCardIdError as exc:
        console.print(f"[red]{console_text(str(exc))}[/red]")
        raise typer.Exit(code=2) from exc
    _print_plan(rows)
    if not confirm:
        console.print("Not started: pass --confirm to run the second engine.")
        return
    engine = engine_factory(device)
    reports = live.run_pending(rows, out_dir, ENGINE_B_NAME, engine, on_row=_report_row)
    flagged = sum(r.status == "review" for r in reports)
    console.print(
        f"Compared {len(reports)} row(s): {flagged} flagged for human review. "
        "Flags mark where the engines differ; they do not say which is right."
    )
