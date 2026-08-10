"""``pursue transcribe run`` — the transcription stage (pipeline stage 8).

Split out of ``commands.py`` (same rationale as ``vision_cli``/``av_fetch_
cli``) to keep that module slim. AUD only — VID is never transcribed
(radar/FLIR has nothing to transcribe); see ``transcribe.eligibility``.

Default run is the **verify-before-spend preflight**: select eligible AUD
items, diff against produced transcript sidecars, print the eligible-vs-
produced report, and exit non-zero on a coverage shortfall — no AAI calls,
no ffprobe. ``--live-smoke <card_id>`` is the ONLY live path: it transcribes
a single card so the AAI client/probe/sidecar chain can be smoke-tested
end-to-end without corpus spend. The bulk corpus run (15 AUD assets) is
operator-attended, invoked directly against ``transcribe.run.run_transcribe``
rather than through this CLI's default path.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pursue_index.cli.worklist import worklist_card_ids
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.transcribe import client, probe
from pursue_index.transcribe.eligibility import EligibleItem, select_eligible
from pursue_index.transcribe.run import (
    TranscribeRunReport,
    preflight_coverage,
    run_transcribe,
)

transcribe_app = typer.Typer(
    name="transcribe", help="Diarized transcription for AUD content (AUD only)."
)
console = Console()

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_WORKLIST = typer.Option(
    None, "--worklist", exists=True, dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "cover the full manifest (the escape hatch).",
)
_OPT_AUDIO_DIR = typer.Option(
    ..., "--audio-dir",
    help="Directory of <card_id>.mp4 source audio files.",
)
_OPT_OUT = typer.Option(
    None, "--out",
    help="Transcript sidecar root (default: settings.ocr_dir — same "
    "consumption path as OCR'd PDFs).",
)
_OPT_LIVE_SMOKE = typer.Option(
    None, "--live-smoke",
    help="THE ONLY LIVE PATH. Transcribe exactly one card_id via AssemblyAI "
    "and write its sidecar — a single-file smoke test. CI never passes this.",
)


def _print_report(report: TranscribeRunReport) -> None:
    console.print(
        f"[cyan]transcribe coverage:[/cyan] {len(report.produced)} produced / "
        f"{len(report.eligible)} eligible"
    )
    if report.missing:
        console.print(
            f"[red]![/red] {len(report.missing)} eligible card(s) have no "
            f"transcript sidecar (operator-attended AAI spend required):"
        )
        for card_id in sorted(report.missing):
            console.print(f"  [red]-[/red] {card_id}")
    for card_id, error in report.failed:
        console.print(f"  [red]x[/red] {card_id}: {error}")


def _live_transcribe_fn(path: Path, *, multichannel: bool) -> client.TranscriptResult:
    return client.transcribe_file(path, multichannel=multichannel)


def _run_live_smoke(
    items: list[EligibleItem], audio_dir: Path, out: Path, card_id: str
) -> None:
    """Transcribe a single card (the smoke target) via the live AAI client."""
    scoped = [i for i in items if i.card_id == card_id]
    if not scoped:
        console.print(f"[red]error:[/red] {card_id!r} is not an eligible AUD item.")
        raise typer.Exit(code=2)
    report = run_transcribe(
        scoped, audio_dir, out,
        transcribe_fn=_live_transcribe_fn,
        probe_fn=probe.is_stereo,
    )
    console.print(
        f"[green]✔[/green] live-smoke wrote {len(report.produced)} card(s) for {card_id}"
    )
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


@transcribe_app.command("run")
def transcribe_run(
    manifest: Path = _OPT_MANIFEST,
    worklist: Path = _OPT_WORKLIST,
    audio_dir: Path = _OPT_AUDIO_DIR,
    out: Path = _OPT_OUT,
    live_smoke: str = _OPT_LIVE_SMOKE,
) -> None:
    """Preflight coverage (default) or a single-card live smoke (``--live-smoke``).

    Default: no spend — reports eligible-vs-produced and exits non-zero on a
    shortfall so a release gate can block on uncovered AUD content.
    """
    m = load_manifest(manifest)
    ids = worklist_card_ids(worklist)
    items = select_eligible(m, ids)
    out_dir = out or settings.ocr_dir

    if live_smoke:
        _run_live_smoke(items, audio_dir, out_dir, live_smoke)
        return

    report = preflight_coverage(items, out_dir)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
