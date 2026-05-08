"""FastAPI search service. Stubbed; implemented in phase 5."""

from __future__ import annotations

from fastapi import FastAPI

from pursue_index import __version__

app = FastAPI(title="pursue-index", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


# TODO(phase-5):
#   GET /cards            list / filter cards (agency, type, dates, location, q)
#   GET /cards/{card_id}  card detail + pages
#   GET /search           full-text search across pages with snippets
#   GET /pdfs/{card_id}   pass-through to source PDF (with attribution headers)
