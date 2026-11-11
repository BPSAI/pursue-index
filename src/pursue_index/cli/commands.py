"""`pursue` CLI — the contract surface for every pipeline stage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from pursue_index import get_logger, scrape
from pursue_index.cli.app_base import PursueApp, console
from pursue_index.cli.scrape_output import print_manifest_summary, print_scrape_diff
from pursue_index.config import settings

log = get_logger(__name__)

app = PursueApp(
    name="pursue",
    help="Searchable index of DOW PURSUE UAP releases.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------
scrape_app = typer.Typer(name="scrape", help="Fetch the source CSV and build a manifest.")
app.add_typer(scrape_app)


@scrape_app.command("fetch-raw")
def scrape_fetch_raw(
    out: Path = typer.Option(
        None,
        "--out",
        help="Path to write the raw CSV. Defaults to data/csv-archive/<timestamp>.csv.",
    ),
) -> None:
    """Download the raw CSV without parsing — useful for diagnostics or archiving."""
    settings.ensure_dirs()
    raw = scrape.fetch_raw_csv()

    if out is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = settings.csv_archive_dir / f"uap-csv-{ts}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    console.print(f"[green]✔[/green] Raw CSV written to {out} ({len(raw)} bytes)")


@scrape_app.command("run")
def scrape_run_cmd(
    out: Path = typer.Option(
        None,
        "--out",
        help="Manifest output path. Defaults to data/manifests/latest.json.",
    ),
    archive_csv: bool = typer.Option(
        True,
        "--archive-csv/--no-archive-csv",
        help="Also save a timestamped copy of the raw CSV to the archive dir.",
    ),
) -> None:
    """Fetch the CSV, parse it, and write a manifest.

    Before overwriting ``latest.json`` we rotate the prior manifest into
    ``data/manifests/snapshots/<csv_sha>.json`` (plus a public mirror at
    ``web/public/data/snapshots/`` for the DiffIsland UI). After the new
    manifest is built we diff it against the snapshot and log any
    removed cards to ``data/removed-cards.jsonl`` — append-only so the
    record survives subsequent scrapes. Removals are surfaced loudly:
    they're the canonical signal that an upstream quiet-pull happened.
    """
    from pursue_index.scrape.snapshots import rotate_and_diff

    settings.ensure_dirs()
    out_path = out or (settings.manifests_dir / "latest.json")

    if archive_csv:
        raw = scrape.fetch_raw_csv()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_path = settings.csv_archive_dir / f"uap-csv-{ts}.csv"
        archive_path.write_bytes(raw)
        log.info("scrape.csv.archived", path=str(archive_path))

    manifest = scrape.run()

    # Rotate the prior latest.json + detect removals BEFORE the new
    # manifest overwrites it. Uses the pydantic model_dump for the diff
    # because manifest is the new model and snapshots/ holds the raw
    # JSON bytes — same shape.
    diff = rotate_and_diff(out_path, manifest.model_dump(by_alias=True))

    scrape.save_manifest(manifest, out_path)

    print_manifest_summary(manifest)
    console.print(f"\n[green]✔[/green] Manifest written to {out_path}")
    print_scrape_diff(diff)


# ---------------------------------------------------------------------------
# sub-apps (download, ocr, embed, vision, av-fetch, transcribe, clean, ops,
# ingest, tranche, storage, provenance, index + serve)
# ---------------------------------------------------------------------------
# Each lives in its own ``*_cli.py`` so this module stays under the per-file
# size and import budgets; ``cli/subapps.py`` attaches them in help order.
from pursue_index.cli.subapps import register_subapps  # noqa: E402

register_subapps(app)


if __name__ == "__main__":
    app()
