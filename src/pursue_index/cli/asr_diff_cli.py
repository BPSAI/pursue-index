"""``pursue transcribe asr-diff run`` -- dry-run cost preview only.

``run`` previews the projected cost of running a second engine over every
AUD row the live plan counts as pending -- the same check
(``asr_diff_rows.card_row_states``), so the two report one
pending/compared/skipped split -- and NEVER calls a second engine itself. The live pass for the
local second engine is ``pursue transcribe asr-diff live``
(``asr_diff_live_cli``), which is a dry run unless given ``--confirm``.
Any other second engine is invoked directly against
``pursue_index.transcribe.asr_diff_runner.run_row`` with the operator's own
client.

A comparison flags where two engines disagree. It does not say which
engine is right, and agreement is not an accuracy score.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index.card_id import InvalidCardIdError, require_card_id
from pursue_index.config import settings
from pursue_index.text_control import console_text
from pursue_index.transcribe.asr_diff_rows import aud_card_ids, card_row_states
from pursue_index.transcribe.asr_diff_runner import estimate_cost_usd

asr_diff_app = typer.Typer(
    name="asr-diff",
    help="Second-engine ASR cross-check for AUD transcripts: run previews cost; live runs the local engine.",
    no_args_is_help=True,
)
console = Console()


def _preview_rows(
    out_dir: Path, card_ids: list[str], engine_b: str,
) -> tuple[list[tuple[str, str, float]], int, int]:
    """``(card_id, row_key, audio_duration_s)`` for every row the live plan
    would compare against ``engine_b``, then how many rows it counts as
    already compared and as skipped (``asr_diff_rows.card_row_states``)."""
    pending: list[tuple[str, str, float]] = []
    compared = skipped = 0
    for card_id in card_ids:
        for row in card_row_states(out_dir / require_card_id(card_id), engine_b):
            if row.state == "pending":
                pending.append((card_id, row.row_key, row.duration_s))
            compared += row.state == "compared"
            skipped += row.state == "skipped"
    return pending, compared, skipped


def _print_dry_run(
    rows: list[tuple[str, str, float]], compared: int, skipped: int,
    engine_b: str, rate_usd_per_minute: float,
) -> None:
    table = Table(title="asr-diff DRY-RUN -- nothing spent")
    table.add_column("Card")
    table.add_column("Row")
    table.add_column("Duration (min)", justify="right")
    table.add_column("Projected cost", justify="right")
    total = 0.0
    for card_id, row_key, duration_s in rows:
        cost = estimate_cost_usd(duration_s, rate_usd_per_minute)
        total += cost
        table.add_row(
            console_text(card_id), console_text(row_key) or "-",
            f"{duration_s / 60:.1f}", f"${cost:.4f}",
        )
    console.print(table)
    console.print(
        f"[yellow]DRY-RUN[/yellow]: {len(rows)} row(s) would be compared against "
        f"[bold]{console_text(engine_b)}[/bold] at ${rate_usd_per_minute:.4f}/min "
        f"-- total projected ${total:.2f}. Nothing was spent. "
        f"{compared} already compared, {skipped} skipped."
    )


@asr_diff_app.command("run")
def asr_diff_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    out: Path | None = typer.Option(
        None, "--out",
        help="Transcript sidecar root (default: settings.ocr_dir).",
    ),
    cards: str | None = typer.Option(
        None, "--cards", help="Comma-separated card_ids. Defaults to every AUD card.",
    ),
    engine_b: str = typer.Option(
        ..., "--engine-b", help="Identifier of the second ASR engine (e.g. a vendor name).",
    ),
    rate_usd_per_minute: float = typer.Option(
        ..., "--rate-usd-per-minute", help="Second engine's per-audio-minute rate.",
    ),
) -> None:
    """Preview the cost of a second-engine pass over every AUD row still
    pending under ``engine_b``. Never spends -- see module docstring."""
    out_dir = out or settings.ocr_dir
    try:
        card_ids = aud_card_ids(manifest, cards)
        rows, compared, skipped = _preview_rows(out_dir, card_ids, engine_b)
    except InvalidCardIdError as exc:
        console.print(f"[red]{console_text(str(exc))}[/red]")
        raise typer.Exit(code=2) from exc
    try:
        _print_dry_run(rows, compared, skipped, engine_b, rate_usd_per_minute)
    except ValueError as exc:  # negative/non-finite duration or rate
        console.print(f"[red]{console_text(str(exc))}[/red]")
        raise typer.Exit(code=2) from exc
