"""`pursue` CLI — the contract surface for every pipeline stage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.scrape import fetch_raw_csv, load_manifest, run as scrape_run, save_manifest

log = get_logger(__name__)
console = Console()

app = typer.Typer(
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
    raw = fetch_raw_csv()

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
    """Fetch the CSV, parse it, and write a manifest."""
    settings.ensure_dirs()
    out_path = out or (settings.manifests_dir / "latest.json")

    if archive_csv:
        raw = fetch_raw_csv()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_path = settings.csv_archive_dir / f"uap-csv-{ts}.csv"
        archive_path.write_bytes(raw)
        log.info("scrape.csv.archived", path=str(archive_path))

    manifest = scrape_run()
    save_manifest(manifest, out_path)

    _print_manifest_summary(manifest)
    console.print(f"\n[green]✔[/green] Manifest written to {out_path}")


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
download_app = typer.Typer(name="download", help="Download assets referenced by a manifest.")
app.add_typer(download_app)


@download_app.command("run")
def download_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
) -> None:
    """Download every PDF/IMG (and optionally video) referenced by ``manifest``."""
    from pursue_index.download.downloader import download_all  # lazy import

    settings.ensure_dirs()
    m = load_manifest(manifest)
    asyncio.run(download_all(m))


# ---------------------------------------------------------------------------
# ocr
# ---------------------------------------------------------------------------
ocr_app = typer.Typer(name="ocr", help="OCR downloaded PDFs.")
app.add_typer(ocr_app)


@ocr_app.command("run")
def ocr_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
) -> None:
    """OCR every PDF that hasn't been processed yet."""
    from pursue_index.ocr.pipeline import ocr_all  # lazy import

    settings.ensure_dirs()
    m = load_manifest(manifest)
    asyncio.run(ocr_all(m))


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------
index_app = typer.Typer(name="index", help="Postgres ingest + search.")
app.add_typer(index_app)


@index_app.command("ingest")
def index_ingest(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
) -> None:
    """Ingest manifest + OCR output into Postgres."""
    from pursue_index.index.ingest import ingest_all  # lazy import

    m = load_manifest(manifest)
    ingest_all(m)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------
@app.command("serve")
def serve(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
) -> None:
    """Run the FastAPI search service."""
    import uvicorn

    uvicorn.run(
        "pursue_index.api.main:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=False,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _print_manifest_summary(manifest) -> None:
    by_agency: dict[str, int] = {}
    by_type: dict[str, int] = {}
    redacted = 0
    for c in manifest.cards:
        by_agency[c.agency] = by_agency.get(c.agency, 0) + 1
        by_type[c.asset_type] = by_type.get(c.asset_type, 0) + 1
        if c.redacted:
            redacted += 1

    summary = Table(title=f"Manifest summary — {manifest.card_count} cards")
    summary.add_column("Agency")
    summary.add_column("Count", justify="right")
    for agency, count in sorted(by_agency.items(), key=lambda kv: -kv[1]):
        summary.add_row(agency, str(count))
    console.print(summary)

    by_type_table = Table(title="By asset type")
    by_type_table.add_column("Type")
    by_type_table.add_column("Count", justify="right")
    for t, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
        by_type_table.add_row(t, str(count))
    console.print(by_type_table)

    console.print(f"Redacted: [bold]{redacted}[/bold] / {manifest.card_count}")


if __name__ == "__main__":
    app()
