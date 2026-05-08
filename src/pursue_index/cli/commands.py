"""`pursue` CLI — the contract surface for every pipeline stage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index.config import settings
from pursue_index import get_logger
from pursue_index.scrape import PlaywrightRunner, load_manifest, save_manifest

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
scrape_app = typer.Typer(name="scrape", help="Scrape the PURSUE index.")
app.add_typer(scrape_app)


@scrape_app.command("inspect")
def scrape_inspect(
    out: Path = typer.Option(
        None,
        "--out",
        help="Directory to write rendered HTML + screenshot.",
    ),
) -> None:
    """Dump rendered DOM for offline selector tuning."""
    settings.ensure_dirs()
    out_dir = out or settings.inspect_dir
    runner = PlaywrightRunner()
    path = asyncio.run(runner.inspect(out_dir))
    console.print(f"[green]✔[/green] Inspect output written to {path}")


@scrape_app.command("run")
def scrape_run(
    out: Path = typer.Option(
        None,
        "--out",
        help="Manifest output path. Defaults to data/manifests/release_01.json.",
    ),
    pages: str = typer.Option(
        "all", "--pages", help='"all" or an integer max-pages cap.'
    ),
) -> None:
    """Build a manifest of every card across all pages."""
    settings.ensure_dirs()
    out_path = out or (settings.manifests_dir / "release_01.json")
    max_pages = None if pages == "all" else int(pages)

    runner = PlaywrightRunner()
    manifest = asyncio.run(runner.run(max_pages=max_pages))
    save_manifest(manifest, out_path)

    _print_manifest_summary(manifest)
    console.print(f"\n[green]✔[/green] Manifest written to {out_path}")


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------
download_app = typer.Typer(name="download", help="Download PDFs referenced by a manifest.")
app.add_typer(download_app)


@download_app.command("run")
def download_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
) -> None:
    """Download all PDFs referenced by ``manifest``."""
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
    table = Table(title=f"Manifest summary ({manifest.card_count} cards)")
    table.add_column("Agency")
    table.add_column("Count", justify="right")

    counts: dict[str, int] = {}
    for c in manifest.cards:
        key = c.agency or "(unknown)"
        counts[key] = counts.get(key, 0) + 1

    for agency, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        table.add_row(agency, str(count))

    console.print(table)


if __name__ == "__main__":
    app()
