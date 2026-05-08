# Architecture

## Goals

1. Build a complete, searchable index of every PURSUE document released by DOW.
2. Re-run incrementally as new tranches drop (every few weeks per DOW's stated cadence).
3. Make every stage independently runnable and assertable — PairCoder will enforce stage contracts.
4. Keep the data layer separate from the code: PDFs and OCR artifacts live on the NAS; the repo carries code, manifest JSON, and DB schema.

## Stages

| # | Stage | Inputs | Outputs | Status |
|---|-------|--------|---------|--------|
| 1 | scrape   | DOW PURSUE page                  | `manifest.json`                       | ✅ implemented |
| 2 | download | manifest                         | PDFs in `data/pdfs/{card_id}/`        | ✅ implemented |
| 3 | ocr      | PDFs                             | `pages.jsonl`, `meta.json` per card   | 🔧 stub |
| 4 | index    | manifest + OCR output            | Postgres rows                         | 🔧 stub |
| 5 | serve    | Postgres                         | FastAPI search API                    | 🔧 stub |

## Idempotency contract

Every stage is idempotent against a content-hashed manifest. Re-running a stage on an unchanged manifest must be a no-op (modulo timestamps). This is what makes the "tranche every few weeks" cadence cheap to support — the new tranche shows up as added cards in the manifest diff, and downstream stages only do net-new work.

## The card_id

`card_id = sha256(pdf_url)[:16]`. Stable across re-scrapes, derived purely from public input, and short enough to use as a directory name on the NAS.

## OCR strategy

Two-engine approach because historical FBI scans vary wildly in quality:

- **Tesseract** locally on the 5090 — fast, free, good enough for clean typewriter scans.
- **Azure Document Intelligence Layout** — strong on faded, skewed, multi-column, and form-like pages. Costs ~$1.50/1k pages.

In `auto` mode, Tesseract runs first; pages with mean confidence below a threshold are re-OCR'd with Azure DI. Engine + confidence are recorded per page so we can re-process selectively if a better OCR option appears.

## Search

Phase 1 uses Postgres full-text search via a `tsvector` column with a GIN index — sufficient for the corpus size and zero new infrastructure. If query-quality on jargon-heavy historical text is poor, we add `pgvector` with locally-generated embeddings (the `embedding` column is already declared in the schema, so it's a straight migration).

## What lives where

- **Repo** — code, `pyproject.toml`, manifests (small JSON), migrations, docs.
- **NAS (`PURSUE_DATA_ROOT`)** — PDFs (`pdfs/`), OCR output (`ocr/`), inspect dumps (`inspect/`), runtime logs.
- **Postgres** — `cards`, `pages`. No blob storage in DB.

## Re-running on a new tranche

```bash
pursue scrape run --out data/manifests/release_02.json
# diff against previous manifest happens implicitly via card_id idempotency
pursue download run --manifest data/manifests/release_02.json
pursue ocr run --manifest data/manifests/release_02.json
pursue index ingest --manifest data/manifests/release_02.json
```

Each stage skips work that's already been done for an unchanged `card_id`. The manifest is the source of truth for what exists; the NAS and DB are derived state.
