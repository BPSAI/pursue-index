"""`pursue` CLI — the contract surface for every pipeline stage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index import get_logger, scrape
from pursue_index.config import settings

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

    _print_manifest_summary(manifest)
    console.print(f"\n[green]✔[/green] Manifest written to {out_path}")
    _print_scrape_diff(diff)


# ---------------------------------------------------------------------------
# download + ocr
# ---------------------------------------------------------------------------
# Split into ``download_ocr_cli.py`` (same rationale as embed_app/ops_app) to
# keep this module slim; that module also owns the T6.5 ``--worklist`` scoping.
from pursue_index.cli.download_ocr_cli import download_app, ocr_app  # noqa: E402

app.add_typer(download_app)
app.add_typer(ocr_app)

# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------
# The embed sub-app is split into ``embed_cli.py`` so this file stays under
# the per-file size budget. Re-attach it here so the CLI surface is unchanged.
from pursue_index.cli.embed_cli import embed_app  # noqa: E402

app.add_typer(embed_app)

# ---------------------------------------------------------------------------
# clean (LLM cleanup of OCR text — pilot-gated)
# ---------------------------------------------------------------------------
# Same split rationale as embed_app/ops_app: keep this module slim. The
# cleanup stage is opt-in and feeds the reader-mode `Cleaned` overlay; it
# never modifies the canonical OCR output.
from pursue_index.cli.clean_cli import clean_app  # noqa: E402

app.add_typer(clean_app)

# ---------------------------------------------------------------------------
# ops (health checks driven by GH Actions cron)
# ---------------------------------------------------------------------------
# Same split rationale as ``embed_app`` — keep this module slim.
from pursue_index.cli.ops_cli import ops_app  # noqa: E402

app.add_typer(ops_app)


# ---------------------------------------------------------------------------
# ingest (tranche-approval gate)
# ---------------------------------------------------------------------------
from pursue_index.cli.ingest_cli import ingest_app  # noqa: E402

app.add_typer(ingest_app)


# ---------------------------------------------------------------------------
# storage (3-tier durability contract preflight)
# ---------------------------------------------------------------------------
from pursue_index.cli.storage_cli import storage_app  # noqa: E402

app.add_typer(storage_app)


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

    m = scrape.load_manifest(manifest)
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
def _print_scrape_diff(diff: dict[str, object]) -> None:
    """Render the rotate / added / removed summary lines for ``scrape run``."""
    if diff["snapshot"]:
        console.print(f"[dim]Prior manifest rotated to snapshot:[/dim] {diff['snapshot']}")
    if diff["added"]:
        console.print(f"[cyan]+[/cyan] {diff['added']} new card(s)")
    if diff["removed"]:
        console.print(
            f"[red]![/red] [bold]{diff['removed']} card(s) REMOVED "
            f"upstream[/bold] — logged to data/removed-cards.jsonl"
        )
        for title in diff["removed_titles"]:
            console.print(f"  [red]-[/red] {title}")


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
