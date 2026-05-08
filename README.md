# pursue-index

A searchable index of the U.S. Department of War's **Presidential Unsealing and Reporting System for UAP Encounters (PURSUE)** document releases.

Source: <https://www.war.gov/UFO/>

## Status

Active build — Release 01 ingestion in progress. New tranches expected every few weeks per DOW; pipeline designed to re-run incrementally against published manifests.

## Pipeline

```
scrape  →  download  →  ocr  →  ingest  →  serve
  │           │          │        │          │
  manifest    PDFs       text     Postgres   FastAPI + UI
  (json)      (NAS)      (json)   (+ FTS)
```

Each stage is independently runnable via the `pursue` CLI and idempotent against a content-hashed manifest, so re-running on a new tranche only does net-new work.

## Quickstart

```bash
# Bootstrap (Python 3.12+)
make install

# Inspect the live page DOM (one-off, for selector tuning)
pursue scrape inspect --out data/inspect/

# Build the manifest of all available cards
pursue scrape run --pages all --out data/manifests/release_01.json

# Download all PDFs referenced by the manifest
pursue download run --manifest data/manifests/release_01.json

# OCR everything that hasn't been processed yet
pursue ocr run --manifest data/manifests/release_01.json

# Ingest into Postgres
pursue index ingest --manifest data/manifests/release_01.json

# Serve the search API
pursue serve --port 8080
```

## Layout

```
pursue-index/
├── config/                     # Pydantic settings, logging
├── src/pursue_index/
│   ├── scrape/                 # Playwright-driven card + modal extraction
│   ├── download/               # PDF retrieval, content-addressable storage
│   ├── ocr/                    # Tesseract local + Azure DI fallback
│   ├── index/                  # SQLAlchemy models, ingest, search
│   ├── api/                    # FastAPI app
│   └── cli/                    # Typer CLI (`pursue`)
├── tests/                      # unit + integration
├── migrations/                 # Alembic
├── scripts/                    # bootstrap, ops helpers
├── docs/                       # architecture, schema, runbook
├── docker-compose.yml          # Postgres + dev dependencies
├── pyproject.toml
├── Makefile
└── README.md
```

## Storage

Raw PDFs and OCR artifacts live on the NAS, not in the repo. The repo holds code, manifests (JSON), and DB schema. Configure paths via `.env` (see `.env.example`).

## Operating model

This repo is built to be run against by [PairCoder](https://bpsaisoftware.com) — the workflow contract is enforced via the standard `pursue` CLI verbs, and every stage emits structured JSON suitable for assertion-based validation.

## License

Source documents are U.S. Government works (public domain). This index code is © BPS AI Software, license TBD.
