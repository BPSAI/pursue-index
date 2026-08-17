"""`pursue index` + `pursue serve` — the Postgres/API runtime surface.

Same split rationale as ``embed_app``/``ops_app``: keep ``commands.py`` slim.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pursue_index import scrape
from pursue_index.config import settings

index_app = typer.Typer(name="index", help="Postgres ingest + search.")


@index_app.command("ingest")
def index_ingest(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
) -> None:
    """Ingest manifest + OCR output into Postgres."""
    from pursue_index.index.ingest import ingest_all  # lazy import

    m = scrape.load_manifest(manifest)
    ingest_all(m)


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
