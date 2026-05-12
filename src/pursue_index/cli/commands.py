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
        raw = fetch_raw_csv()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive_path = settings.csv_archive_dir / f"uap-csv-{ts}.csv"
        archive_path.write_bytes(raw)
        log.info("scrape.csv.archived", path=str(archive_path))

    manifest = scrape_run()

    # Rotate the prior latest.json + detect removals BEFORE the new
    # manifest overwrites it. Uses the pydantic model_dump for the diff
    # because manifest is the new model and snapshots/ holds the raw
    # JSON bytes — same shape.
    diff = rotate_and_diff(out_path, manifest.model_dump(by_alias=True))

    save_manifest(manifest, out_path)

    _print_manifest_summary(manifest)
    console.print(f"\n[green]✔[/green] Manifest written to {out_path}")
    if diff["snapshot"]:
        console.print(
            f"[dim]Prior manifest rotated to snapshot:[/dim] "
            f"{diff['snapshot']}"
        )
    if diff["added"]:
        console.print(f"[cyan]+[/cyan] {diff['added']} new card(s)")
    if diff["removed"]:
        console.print(
            f"[red]![/red] [bold]{diff['removed']} card(s) REMOVED "
            f"upstream[/bold] — logged to data/removed-cards.jsonl"
        )
        for title in diff["removed_titles"]:
            console.print(f"  [red]-[/red] {title}")


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
    engine: str = typer.Option(
        None,
        "--engine",
        help="OCR engine: 'tesseract' (CPU), 'surya' (GPU), 'llm' "
        "(Anthropic vision), or 'auto' (primary + LLM fallback for "
        "low-confidence pages). Defaults to PURSUE_OCR_ENGINE.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-OCR cards even if meta.json says status=ok. Required to "
        "re-run a card with a different engine.",
    ),
) -> None:
    """OCR every PDF that hasn't been processed yet."""
    from pursue_index.ocr.pipeline import ocr_all  # lazy import

    settings.ensure_dirs()
    m = load_manifest(manifest)
    asyncio.run(ocr_all(m, engine=engine, force=force))


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
# novelty
# ---------------------------------------------------------------------------
novelty_app = typer.Typer(
    name="novelty",
    help="Compare PURSUE embeddings against a prior-disclosure reference corpus.",
)
app.add_typer(novelty_app)


def _resolve_pursue_embed_dir(model: str | None) -> Path:
    chosen_model = model or settings.embed_model
    pursue_embed_dir = settings.embeddings_dir / chosen_model
    if not (pursue_embed_dir / "index.json").exists():
        console.print(
            f"[red]error:[/red] no PURSUE embed index at {pursue_embed_dir}; "
            "run 'pursue embed run' first."
        )
        raise typer.Exit(code=2)
    return pursue_embed_dir


@novelty_app.command("compute")
def novelty_compute(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    reference: Path = typer.Option(
        ...,
        "--reference",
        help="Path to the per-model reference embed dir (e.g. "
        "data/reference/synthetic/embeddings/voyage-3).",
    ),
    archive_id: str = typer.Option(
        None,
        "--archive-id",
        help="Identifier for the reference corpus (defaults to its parent dir name).",
    ),
    out: Path = typer.Option(
        Path("data/novelty/latest.json"),
        "--out",
        help="Sidecar JSON output path (default: data/novelty/latest.json).",
    ),
    threshold_high: float = typer.Option(
        0.85, "--threshold-high", help="Cosine threshold for previously-disclosed."
    ),
    threshold_partial: float = typer.Option(
        0.70, "--threshold-partial", help="Cosine threshold below which pages are novel."
    ),
    model: str = typer.Option(
        None, "--model", help="Embedding model id (defaults to PURSUE_EMBED_MODEL)."
    ),
) -> None:
    """Run cosine top-1 + aggregation, writing the disclosure sidecar."""
    from pursue_index.novelty.aggregate import Thresholds  # lazy
    from pursue_index.novelty.pipeline import compute_novelty

    settings.ensure_dirs()
    load_manifest(manifest)
    pursue_embed_dir = _resolve_pursue_embed_dir(model)
    chosen_archive = archive_id or reference.parent.parent.name
    report = compute_novelty(
        pursue_embed_dir=pursue_embed_dir,
        reference_embed_dir=reference,
        archive_id=chosen_archive,
        out_path=out,
        thresholds=Thresholds(high=threshold_high, partial=threshold_partial),
    )
    console.print(
        f"[green]✔[/green] novelty: {report.cards_processed} cards, "
        f"{report.pages_compared} pages compared against archive "
        f"[bold]{report.archive_id}[/bold] → {out}"
    )


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
