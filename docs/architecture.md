# Architecture

## Goals

1. Build a complete, searchable index of every PURSUE entry released by DOW.
2. Re-run incrementally as new tranches drop. The DOW publishes a single CSV that gets updated in place; we snapshot it on each run and diff against prior snapshots.
3. Make every stage independently runnable and assertable — PairCoder will enforce stage contracts.
4. Keep the data layer separate from the code: PDFs, images, video, OCR artifacts, and CSV archives all live on the NAS. The repo carries code, manifest JSON, and DB schema.

## Data source

The DOW PURSUE page (`https://www.war.gov/UFO/`) is just a DataTables widget rendering [`uap-csv.csv`](https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv). We fetch that CSV directly. No browser automation, no DOM scraping.

CSV columns we consume:

| CSV column          | Notes                                                          |
|---------------------|----------------------------------------------------------------|
| Redaction           | "True" or empty — boolean ``redacted``                         |
| Release Date        |                                                                |
| Title               | Wrapped in newlines in source; we trim                         |
| Type                | PDF / VID / IMG (6 rows have trailing space — we normalize)    |
| Video Pairing       | Free-text reference to a paired video card                     |
| PDF Pairing         | Free-text reference to a paired PDF card                       |
| Description Blurb   | Full case description (what the modal shows on the page)       |
| DVIDS Video ID      | Present on video entries; uses DVIDS streaming API             |
| Video Title         |                                                                |
| Agency              | DOW / FBI / NASA / DOS                                         |
| Incident Date       | "N/A" treated as null                                          |
| Incident Location   | "N/A" treated as null                                          |
| PDF \| Image Link   | Direct asset URL                                               |
| Modal Image         | Thumbnail shown in the card and modal                          |

## Stages

| # | Stage    | Inputs                | Outputs                              | Status |
|---|----------|-----------------------|--------------------------------------|--------|
| 1 | scrape   | DOW CSV               | `manifest.json`                      | ✅     |
| 2 | download | manifest              | PDFs/IMGs in `data/{pdfs,images}/`   | ✅     |
| 3 | ocr      | PDFs                  | `pages.jsonl` per card               | 🔧 stub |
| 4 | index    | manifest + OCR output | Postgres rows                        | 🔧 stub |
| 5 | serve    | Postgres              | FastAPI search API                   | 🔧 stub |

## Idempotency contract

Every stage is idempotent against a content-hashed manifest. The manifest carries `csv_sha256` (hash of raw bytes) so we can detect upstream changes cheaply. Re-running on an unchanged manifest is a no-op modulo timestamps.

## The card_id

`card_id = sha256(asset_url || title)[:16]`. The URL is the primary stable identifier; title is the fallback for any hypothetical metadata-only entries. Short enough to use as a directory name on the NAS.

## Multi-modal handling

Not every PURSUE entry is a PDF. Of the 161 in Release 01: 119 PDFs, 28 videos, 14 images.

- **PDFs**: download → OCR → index. Standard flow.
- **Images**: download → store. Future: vision analysis (the DOW shipped these as raw infrared stills; OCR isn't useful but visual feature extraction may be).
- **Videos**: hosted on DVIDS, requires a separate API to resolve a download URL. Off by default (`PURSUE_DOWNLOAD_VIDEOS=false`); when on, we fetch via DVIDS API and optionally pull captions/transcripts.

## OCR strategy

Two-engine approach because historical FBI scans vary wildly in quality:

- **Tesseract** locally on the 5090 — fast, free, good enough for clean typewriter scans.
- **Azure Document Intelligence Layout** — strong on faded, skewed, multi-column, and form-like pages. Costs ~$1.50/1k pages.

In `auto` mode, Tesseract runs first; pages with mean confidence below threshold are re-OCR'd with Azure DI. Engine + confidence are recorded per page.

## Search

Phase 1: Postgres full-text search via a `tsvector` column with a GIN index. Phase 2 (if needed): pgvector for semantic search.

## What lives where

- **Repo**: code, `pyproject.toml`, manifests (small JSON, version-controlled), migrations, docs.
- **NAS** (`PURSUE_DATA_ROOT`): `pdfs/`, `images/`, `videos/`, `ocr/`, `csv-archive/` (timestamped raw CSV snapshots), `logs/`.
- **Postgres**: `cards`, `pages`. No blobs in DB.

The split is enforced by config: `PURSUE_DATA_ROOT` and `PURSUE_MANIFESTS_DIR` are independent, so manifests stay in the repo regardless of where bulk data is parked.

## Re-running on a new tranche

The CSV URL is stable; DOW updates the file in place when new tranches drop.

```bash
pursue scrape run                          # writes data/manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json
pursue index ingest --manifest data/manifests/latest.json
```

Each stage skips work it's already done for unchanged `card_id`s. The CSV archive (`data/csv-archive/uap-csv-<timestamp>.csv`) gives us a forensic trail of how the source has evolved over time, independent of the manifests we generate.
