"""Attach the ``pursue`` sub-apps to the root app, in ``--help`` order.

Split out of ``cli/commands.py`` so that module stays under the per-file size
and import budgets; the CLI surface is unchanged.
"""

from __future__ import annotations

import typer

from pursue_index.cli.av_fetch_cli import av_fetch_app
from pursue_index.cli.clean_cli import clean_app
from pursue_index.cli.download_ocr_cli import download_app, ocr_app
from pursue_index.cli.embed_cli import embed_app
from pursue_index.cli.index_serve_cli import index_app, serve
from pursue_index.cli.ingest_cli import ingest_app
from pursue_index.cli.ops_cli import ops_app
from pursue_index.cli.provenance_cli import provenance_app
from pursue_index.cli.storage_cli import storage_app
from pursue_index.cli.tranche_cli import tranche_app
from pursue_index.cli.transcribe_cli import transcribe_app
from pursue_index.cli.vision_cli import vision_app


def register_subapps(app: typer.Typer) -> None:
    """Register every sub-app (and the ``serve`` command) on ``app``."""
    # download + ocr
    # Split into ``download_ocr_cli.py`` (same rationale as embed_app/ops_app) to
    # keep this module slim; that module also owns the ``--worklist`` scoping.
    app.add_typer(download_app)
    app.add_typer(ocr_app)

    # embed
    # The embed sub-app is split into ``embed_cli.py`` so this file stays under
    # the per-file size budget. Re-attach it here so the CLI surface is unchanged.
    app.add_typer(embed_app)

    # vision (per-tranche image-observation generator — pipeline stage 6)
    # Same split rationale as embed_app/ops_app: keep this module slim. The default
    # `vision run` is a verify-before-spend preflight; live spend is operator-
    # attended (see cli/vision_cli.py).
    app.add_typer(vision_app)

    # av-fetch (DVIDS A/V direct-fetch stage — pipeline stage 3)
    # Same split rationale as embed_app/ops_app: keep this module slim. Automates
    # the operator's manual DVIDS download step; output feeds
    # scripts/ingest_release_videos.py --desktop unchanged.
    app.add_typer(av_fetch_app)

    # transcribe (direct AssemblyAI transcription, AUD only — pipeline stage 7)
    # Same split rationale as embed_app/ops_app: keep this module slim. The
    # default `transcribe run` is a verify-before-spend preflight; live spend is
    # operator-attended (see cli/transcribe_cli.py).
    app.add_typer(transcribe_app)

    # clean (LLM cleanup of OCR text — pilot-gated)
    # Same split rationale as embed_app/ops_app: keep this module slim. The
    # cleanup stage is opt-in and feeds the reader-mode `Cleaned` overlay; it
    # never modifies the canonical OCR output.
    app.add_typer(clean_app)

    # ops (health checks driven by GH Actions cron)
    # Same split rationale as ``embed_app`` — keep this module slim.
    app.add_typer(ops_app)

    # ingest (tranche-approval gate)
    app.add_typer(ingest_app)

    # tranche (unattended local promote of a metadata-only tranche)
    app.add_typer(tranche_app)

    # storage (3-tier durability contract preflight)
    app.add_typer(storage_app)

    # provenance (Phase-A coverage report — read-only, publishes nothing)
    app.add_typer(provenance_app)

    # index + serve (Postgres/API runtime)
    # Same split rationale as embed_app/ops_app: keep this module slim.
    app.add_typer(index_app)
    app.command("serve")(serve)
