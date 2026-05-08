# Project Context

## What Is This Project?

**Project:** pursue-index
**Primary Goal:** Build a searchable, re-runnable index of every entry in the
U.S. Department of War's PURSUE (Presidential Unsealing and Reporting System
for UAP Encounters) document release. Source page: <https://www.war.gov/UFO/>.

The DOW publishes new tranches every few weeks. The pipeline is designed to
re-run incrementally against each refresh of the source CSV.

## Pipeline

```
scrape  →  download  →  ocr  →  ingest  →  serve
  │           │          │        │          │
  manifest    PDFs/IMGs  text     Postgres   FastAPI + UI
  (json)      (NAS)      (jsonl)  (+ FTS)
```

Each stage is independently runnable via the `pursue` CLI and idempotent
against a content-hashed manifest.

## Repository Structure

```
pursue-index/
├── .paircoder/                 # PairCoder system files
├── .claude/                    # Claude Code integration (skills, hooks)
├── src/pursue_index/
│   ├── scrape/                 # CSV fetch + parse + manifest build
│   ├── download/               # PDF/IMG retrieval (httpx + tenacity)
│   ├── ocr/                    # Tesseract local + Azure DI fallback
│   ├── index/                  # SQLAlchemy models, ingest, search
│   ├── api/                    # FastAPI app
│   ├── cli/                    # Typer CLI (`pursue`)
│   └── config/                 # Pydantic settings
├── tests/                      # unit + integration
├── migrations/                 # Alembic
├── scripts/                    # bootstrap, ops helpers
├── docs/architecture.md        # canonical architecture doc
├── docker-compose.yml          # Postgres for local dev
└── pyproject.toml
```

## Tech Stack

- **Language:** Python 3.12
- **CLI:** Typer + Rich
- **Settings:** pydantic + pydantic-settings (env-driven, `PURSUE_*` prefix)
- **HTTP:** httpx + tenacity
- **DB:** Postgres + SQLAlchemy 2.x + Alembic
- **OCR:** pytesseract (local) + Azure Document Intelligence (fallback)
- **API:** FastAPI + uvicorn
- **Tests:** pytest + pytest-asyncio
- **Lint/Type:** ruff + mypy (strict)

## Data Source

The DOW PURSUE page is a DataTables widget rendering a single CSV:
`https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv`. We fetch
that CSV directly — no DOM scraping, no Playwright. The CSV URL is stable;
DOW updates the file in place when new tranches drop.

CSV columns we consume: Redaction, Release Date, Title, Type (PDF/VID/IMG),
Video Pairing, PDF Pairing, Description Blurb, DVIDS Video ID, Video Title,
Agency, Incident Date, Incident Location, PDF | Image Link, Modal Image.

## Storage Split

Two independent paths so manifests stay in the repo and bulk data goes to NAS:

| Path                    | Holds                                               |
|-------------------------|-----------------------------------------------------|
| `PURSUE_DATA_ROOT`      | PDFs, images, videos, OCR output, raw CSV archives |
| `PURSUE_MANIFESTS_DIR`  | Manifest JSON (small, version-controlled)           |

In production, `PURSUE_DATA_ROOT` points at the NAS mount on `buschleague`
(currently `/mnt/nas/personal/pursue`). Manifests stay under `./data/manifests`
and are committed.

## Idempotency

`card_id = sha256(asset_url || title)[:16]`. The manifest carries
`csv_sha256` so we can detect upstream changes cheaply. Re-running on an
unchanged manifest is a no-op modulo timestamps.

## Key Constraints

| Constraint        | Requirement                                              |
|-------------------|----------------------------------------------------------|
| **Test Coverage** | 80% target                                               |
| **Architecture**  | `bpsai-pair arch check` enforces 400-line/50-fn limits   |
| **Secrets**       | Never commit `.env` (tracked: `.env.example`)            |
| **Source data**   | Public domain US Government works                        |
| **Code license**  | © BPS AI Software, license TBD                           |

## Architecture Principles

1. **Stage isolation** — each pipeline stage is independently runnable and emits
   structured JSON; PairCoder enforces stage contracts.
2. **Code/data split** — repo holds code + manifests + DB schema; NAS holds blobs.
3. **Idempotent re-runs** — content-hashed manifest enables cheap diffs.
4. **Test-driven** — write failing tests first; see `implementing-with-tdd` skill.

## How to Work Here

1. Read `.paircoder/context/state.md` for current plan/task status.
2. Check `.paircoder/capabilities.yaml` for available actions.
3. Follow the active skill for structured work (see `.claude/skills/`).
4. Update `state.md` after completing significant work.
5. Run `bpsai-pair arch check <path>` before completing any code task.

## Key Files

| File                               | Purpose                                |
|------------------------------------|----------------------------------------|
| `.paircoder/config.yaml`           | Project configuration                  |
| `.paircoder/context/state.md`      | Current status and active work         |
| `docs/architecture.md`             | Canonical architecture doc             |
| `src/pursue_index/scrape/csv_fetcher.py` | CSV fetch entry point            |
| `src/pursue_index/cli/commands.py` | Typer CLI surface                      |
| `pyproject.toml`                   | Dependencies + tool config             |
| `.env.example`                     | Env var contract                       |
