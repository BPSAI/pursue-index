"""``pursue download`` + ``pursue ocr`` executors.

Split out of ``commands.py`` (same rationale as ``embed_cli`` / ``ops_cli``) to
keep that module under its import/size budget — and the natural home for the
T6.5 ``--worklist`` scoping wired into both heavy stages here. The CLI surface is
unchanged: ``commands.py`` re-attaches ``download_app`` / ``ocr_app``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from pursue_index.cli.worklist import apply_worklist
from pursue_index.config import settings
from pursue_index.scrape import load_manifest

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_WORKLIST = typer.Option(
    None,
    "--worklist",
    exists=True,
    dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "process the full manifest (the escape hatch). Written by `ingest run --from-diff`.",
)

download_app = typer.Typer(name="download", help="Download assets referenced by a manifest.")


@download_app.command("run")
def download_run(
    manifest: Path = _OPT_MANIFEST,
    worklist: Path = _OPT_WORKLIST,
) -> None:
    """Download every PDF/IMG (and optionally video) referenced by ``manifest``."""
    from pursue_index.download.downloader import download_all  # lazy import

    settings.ensure_dirs()
    m = apply_worklist(load_manifest(manifest), worklist)
    asyncio.run(download_all(m))


ocr_app = typer.Typer(name="ocr", help="OCR downloaded PDFs.")


@ocr_app.command("run")
def ocr_run(
    manifest: Path = _OPT_MANIFEST,
    engine: str = typer.Option(
        None,
        "--engine",
        help="OCR engine. Operated: 'llm-dots' (Sonnet 4.6 vision primary + "
        "per-page local dots.mocr fallback on a content-filter 400 — needs "
        "PURSUE_DOTS_PYTHON). Also selectable: 'dots' (dots.mocr alone), 'llm' "
        "(Anthropic vision alone). Retired (do not use): 'tesseract', 'surya', "
        "'auto'. Defaults to PURSUE_OCR_ENGINE (llm-dots).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-OCR cards even if meta.json says status=ok. Required to "
        "re-run a card with a different engine.",
    ),
    concurrency: int = typer.Option(
        None,
        "--concurrency",
        help="Override card-level concurrency. Operated: --engine llm-dots --concurrency 8 "
        "(also PURSUE_OCR_LLM_CONCURRENCY env var); defaults to 8 if unset. Set 1 to force serial.",
    ),
    worklist: Path = _OPT_WORKLIST,
) -> None:
    """OCR every PDF that hasn't been processed yet."""
    from pursue_index.ocr.pipeline import ocr_all  # lazy import

    settings.ensure_dirs()
    m = apply_worklist(load_manifest(manifest), worklist)
    asyncio.run(ocr_all(m, engine=engine, force=force, concurrency=concurrency))
