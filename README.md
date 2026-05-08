# pursue-index

A searchable index of the U.S. Department of War's **Presidential Unsealing
and Reporting System for UAP Encounters (PURSUE)** document releases.

Source: <https://www.war.gov/UFO/>

## What this is

DOW publishes the PURSUE corpus as a single CSV
(`uap-csv.csv`) rendered into a DataTables widget on the public page. New
tranches drop every few weeks; the file is updated in place. This project:

1. **Snapshots the upstream CSV** on each run and archives it for forensic
   diffing.
2. **Builds a content-hashed manifest** so re-runs only do net-new work.
3. **Pulls the referenced PDFs and images** to local/NAS storage.
4. **OCRs every PDF** to a per-page JSON Lines file.
5. **Ingests** the manifest + OCR output into Postgres for full-text search.
6. **Serves** a search API (and eventually a UI) over the index.

Each stage is independently runnable via the `pursue` CLI and idempotent
against the manifest, so re-running on a new tranche only touches new entries.

## Pipeline

```
scrape  →  download  →  ocr  →  index  →  serve
  │           │          │       │         │
  manifest    PDFs/IMGs  text    Postgres  FastAPI + UI
  (json)      (NAS)      (jsonl) (+ FTS)
```

| Stage    | Status | Output                                              |
|----------|--------|-----------------------------------------------------|
| scrape   | ✅     | `data/manifests/latest.json`                        |
| download | ✅     | `{pdfs,images,videos}/{card_id}/{filename}` on NAS  |
| ocr      | ✅ v1  | `ocr/{card_id}/{pages.jsonl, meta.json}` on NAS     |
| index    | 🔧 stub | Postgres rows with `tsvector` FTS                  |
| serve    | 🔧 stub | FastAPI search API                                 |

See [`docs/architecture.md`](docs/architecture.md) for the full design.

## Quickstart

Requires Python 3.12+, Postgres (for the eventual `index` and `serve` stages),
and the `tesseract` system binary for OCR.

```bash
# Bootstrap a venv and install
make install

# System dep for OCR (one-time)
sudo apt install tesseract-ocr tesseract-ocr-eng poppler-utils

# Copy and edit config
cp .env.example .env
$EDITOR .env   # at minimum, set PURSUE_DATA_ROOT

# Pipeline
pursue scrape run                                    # writes data/manifests/latest.json
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json
pursue index ingest --manifest data/manifests/latest.json   # (stub)
pursue serve --port 8080                                    # (stub)
```

The full Release 01 corpus is **161 cards** (119 PDFs / 28 videos / 14 images),
~2.4 GB on disk after `download`, and produces ~4–6k OCR pages.

## Why curl_cffi for scrape

The CSV endpoint is gated by Akamai bot management on TLS fingerprint and
HTTP/2 framing — plain `httpx`/`requests` clients get a 403, even with the
full Chrome client-hint header set. We use
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) with
`impersonate="chrome"` so the handshake looks identical to a real Chrome
session. The asset URLs (PDFs, images) are served by a more permissive Akamai
config and work fine over plain `httpx`, so the downloader doesn't need TLS
impersonation.

## Storage split

The repo holds **code, manifests, and DB schema only**. Bulk artifacts live
on the NAS via two independent env vars:

| Var                     | Holds                                              |
|-------------------------|----------------------------------------------------|
| `PURSUE_DATA_ROOT`      | PDFs, images, videos, OCR output, raw CSV archives |
| `PURSUE_MANIFESTS_DIR`  | Manifest JSON (small, version-controlled)          |

In production, `PURSUE_DATA_ROOT` is the NAS mount and `PURSUE_MANIFESTS_DIR`
stays inside the repo so manifests are committed alongside the code that
produced them.

## Idempotency contract

- `card_id = sha256(asset_url || title)[:16]` — stable across re-fetches.
- Manifest carries `csv_sha256` (hash of raw CSV bytes) so we can detect
  upstream changes cheaply.
- Each stage skips work it's already done for unchanged `card_id`s.
- The CSV archive (`{data_root}/csv-archive/uap-csv-<timestamp>.csv`) is a
  forensic trail of how the source has evolved over time.

## Repo layout

```
pursue-index/
├── src/pursue_index/
│   ├── scrape/          # CSV fetch (curl_cffi) + parse + manifest
│   ├── download/        # Asset retrieval, content-addressable storage
│   ├── ocr/             # Tesseract pipeline → pages.jsonl + meta.json
│   ├── index/           # SQLAlchemy models, ingest, search (WIP)
│   ├── api/             # FastAPI app (WIP)
│   ├── cli/             # Typer CLI (`pursue`)
│   └── config/          # Pydantic settings (env-driven, PURSUE_* prefix)
├── tests/               # unit + integration
├── migrations/          # Alembic
├── scripts/             # bootstrap, ops helpers
├── docs/                # architecture, schema, runbook
├── docker-compose.yml   # Postgres for local dev
├── pyproject.toml
└── Makefile
```

## Development

```bash
# Run tests
pytest

# Type-check
mypy src/

# Lint
ruff check src/
```

This repo is built to run against [PairCoder](https://bpsaisoftware.com).
The workflow contract is enforced via the standard `pursue` CLI verbs, and
every stage emits structured JSON suitable for assertion-based validation.
See `.paircoder/context/` for plan/state docs and `.claude/skills/` for the
agent workflow surface.

## License

Source documents are U.S. Government works (public domain). This index code
is © BPS AI Software, license TBD.
