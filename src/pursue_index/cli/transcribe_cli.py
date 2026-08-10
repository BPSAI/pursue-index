"""``pursue transcribe run`` — the transcription stage.

Split out of ``commands.py`` (same rationale as ``vision_cli``/``av_fetch_
cli``) to keep that module slim. AUD only — VID is never transcribed
(radar/FLIR has nothing to transcribe); see ``transcribe.eligibility``.

Scope is a release: ``--release-date`` selects the AUD rows of one tranche,
the same field ``av-fetch`` uses to reach the same rows, because AUD rows
carry no ``asset_url`` and so never appear in a tranche work list. Omitting
it covers the whole manifest.

Default run is the **verify-before-spend preflight**: select eligible AUD
rows, diff against produced transcripts, print the eligible-vs-produced
report, and exit non-zero on a coverage shortfall — no AAI calls, no ffprobe,
and no source audio needed. ``--live-smoke <card_id>`` is the ONLY live path:
it transcribes a single card so the AAI client/probe/sidecar chain can be
smoke-tested end-to-end without corpus spend. The bulk pass is
operator-attended, invoked directly against ``transcribe.run.run_transcribe``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

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
_OPT_RELEASE_DATE = typer.Option(
    None, "--release-date",
    help="Manifest release_date to scope to (matches av-fetch). Omit to cover "
    "the full manifest (the escape hatch).",
)
_OPT_AUDIO_DIR = typer.Option(
    None, "--audio-dir",
    help="Directory of source audio files, one per eligible row. Required "
    "only for --live-smoke; the preflight reads sidecars alone.",
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


def _unit_label(card_id: str, row_key: str) -> str:
    """One coverage unit, naming its row only when the card_id has more than one."""
    return f"{card_id}{f' [{row_key}]' if row_key else ''}"


def _print_report(report: TranscribeRunReport) -> None:
    console.print(
        f"[cyan]transcribe coverage:[/cyan] {len(report.produced)} produced / "
        f"{len(report.eligible)} eligible"
    )
    if report.empty:
        console.print(
            f"[red]![/red] {len(report.empty)} row(s) returned a transcript with "
            f"no content and remain uncovered:"
        )
        for card_id, row_key in report.empty:
            console.print(f"  [red]-[/red] {_unit_label(card_id, row_key)}")
    if report.missing:
        console.print(
            f"[red]![/red] {len(report.missing)} eligible row(s) have no "
            f"transcript (operator-attended AAI spend required):"
        )
        for card_id, row_key in sorted(report.missing):
            console.print(f"  [red]-[/red] {_unit_label(card_id, row_key)}")
    for (card_id, row_key), error in report.failed:
        console.print(f"  [red]x[/red] {_unit_label(card_id, row_key)}: {error}")


def _live_transcribe_fn(path: Path, *, multichannel: bool) -> client.TranscriptResult:
    return client.transcribe_file(path, multichannel=multichannel)


def _run_live_smoke(
    items: list[EligibleItem], audio_dir: Path | None, out: Path, card_id: str
) -> None:
    """Transcribe a single card (the smoke target) via the live AAI client."""
    if audio_dir is None:
        console.print("[red]error:[/red] --live-smoke reads source audio; pass --audio-dir.")
        raise typer.Exit(code=2)
    scoped = [i for i in items if i.card_id == card_id]
    if not scoped:
        console.print(f"[red]error:[/red] {card_id!r} is not an eligible AUD row.")
        raise typer.Exit(code=2)
    report = run_transcribe(
        scoped, audio_dir, out,
        transcribe_fn=_live_transcribe_fn,
        probe_fn=probe.is_stereo,
    )
    console.print(
        f"[green]✔[/green] live-smoke wrote {len(report.produced)} row(s) for {card_id}"
    )
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


@transcribe_app.command("run")
def transcribe_run(
    manifest: Path = _OPT_MANIFEST,
    release_date: str = _OPT_RELEASE_DATE,
    audio_dir: Path = _OPT_AUDIO_DIR,
    out: Path = _OPT_OUT,
    live_smoke: str = _OPT_LIVE_SMOKE,
) -> None:
    """Preflight coverage (default) or a single-card live smoke (``--live-smoke``).

    Default: no spend — reports eligible-vs-produced and exits non-zero on a
    shortfall so a release gate can block on uncovered AUD content.
    """
    m = load_manifest(manifest)
    items = select_eligible(m, release_date)
    out_dir = out or settings.ocr_dir

    if live_smoke:
        _run_live_smoke(items, audio_dir, out_dir, live_smoke)
        return

    report = preflight_coverage(items, out_dir)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
