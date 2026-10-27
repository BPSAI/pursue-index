"""``pursue transcribe asr-diff run`` -- dry-run cost preview only.

Spend on the second-engine ASR cross-check (R7C.27) is operator-attended:
this command previews the projected cost of running a second engine over
every AUD row that does not yet carry a completed comparison under the
given engine pair, and NEVER calls a second engine itself -- no vendor is
wired into this CLI. The live pass is invoked directly against
``pursue_index.transcribe.asr_diff_runner.run_row`` with the operator's own
second-engine client, the same way the bulk transcribe pass bypasses
``pursue transcribe run`` (see that command's docstring).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index.card_id import InvalidCardIdError, require_card_id, require_card_ids
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.text_control import console_text
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff_runner import estimate_cost_usd

asr_diff_app = typer.Typer(
    name="asr-diff",
    help="Second-engine ASR cross-check for AUD transcripts (dry-run cost preview only).",
    no_args_is_help=True,
)
console = Console()


def _aud_card_ids(manifest_path: Path, cards_filter: str | None) -> list[str]:
    wanted = (
        set(require_card_ids(c.strip() for c in cards_filter.split(",") if c.strip()))
        if cards_filter else None
    )
    manifest = load_manifest(manifest_path)
    aud_cards = [c.card_id for c in manifest.cards if c.asset_type == "AUD"]
    if wanted is not None:
        aud_cards = [c for c in aud_cards if c in wanted]
    return aud_cards


def _read_meta(card_dir: Path) -> dict | None:
    meta_path = card_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _eligible_rows(
    out_dir: Path, card_ids: list[str], engine_b: str,
) -> list[tuple[str, str, float]]:
    """``(card_id, row_key, audio_duration_s)`` for every AUD row carrying a
    transcript but no completed comparison against ``engine_b`` yet."""
    rows: list[tuple[str, str, float]] = []
    for card_id in card_ids:
        card_dir = out_dir / require_card_id(card_id)
        meta = _read_meta(card_dir)
        if not meta or meta.get("status") != "ok":
            continue
        engine_a = meta.get("engine", "")
        existing = sidecar.load_existing(card_dir / sidecar.SIDECAR_FILE)
        version = sidecar.transcript_version(card_dir)
        for row in meta.get("rows") or [{"row_key": ""}]:
            row_key = str(row.get("row_key", "") or "")
            prior = existing.get(row_key)
            if prior and sidecar.should_skip(
                prior, engine_a=engine_a, engine_b=engine_b, transcript_version=version,
            ):
                continue
            duration_s = float(row.get("audio_duration_s") or 0.0)
            rows.append((card_id, row_key, duration_s))
    return rows


def _print_dry_run(
    rows: list[tuple[str, str, float]], engine_b: str, rate_usd_per_minute: float,
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
        f"-- total projected ${total:.2f}. Nothing was spent."
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
    """Preview the cost of a second-engine pass over every AUD row not yet
    compared under ``engine_b``. Never spends -- see module docstring."""
    out_dir = out or settings.ocr_dir
    try:
        card_ids = _aud_card_ids(manifest, cards)
        rows = _eligible_rows(out_dir, card_ids, engine_b)
    except InvalidCardIdError as exc:
        console.print(f"[red]{console_text(str(exc))}[/red]")
        raise typer.Exit(code=2) from exc
    _print_dry_run(rows, engine_b, rate_usd_per_minute)
