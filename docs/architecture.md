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

Historical FBI scans vary wildly in quality, so we plan for a multi-engine
approach. The current implementation is **Tesseract-only (v1)**; the engine
seam in `ocr/pipeline.py` (`rasterize_pdf`, `ocr_image`, `_run_engine`) is
deliberately engine-agnostic so additional engines can land without
disturbing orchestration.

- **Tesseract** (current default) — local CPU OCR. Fast, free, good enough
  for clean typewriter scans. Note: Tesseract is CPU-only; the GPU on the
  workstation is unused by this engine.
- **GPU OCR** (planned) — modern transformer-based OCR (Surya is the leading
  candidate) running on the local 5090 would dramatically outperform
  Tesseract on faded, skewed, multi-column FBI scans, and likely cut
  wall-clock by 5–20× on long PDFs.
- **LLM extraction** (planned) — Anthropic / OpenAI vision models as the
  high-quality fallback for pages where Tesseract confidence is low. This
  replaces what an earlier draft of this doc called out as Azure Document
  Intelligence; LLM extraction gives us better output for less integration
  surface and no model-training overhead.

In the eventual `auto` mode, Tesseract (or Surya) runs first; pages with
mean confidence below threshold are re-extracted via the LLM fallback.
Engine + confidence are recorded per page in `pages.jsonl`.

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

## Web build chain (post-embed)

The static site shipped to Cloudflare reads three browser-side payloads
that derive from the embed/index outputs. They have an implicit
ordering: a fresh `pursue embed run` invalidates all three, and the web
build must rebuild them all before re-deploying or the rendered pages
will reference deduped rows that don't exist in the deployed payload.

| # | Script                              | Reads                                                | Writes                                            |
|---|-------------------------------------|------------------------------------------------------|---------------------------------------------------|
| 1 | `pursue embed run`                  | OCR pages + manifest                                 | `{embeddings_root}/{model}/{vectors.bin,index.json}` |
| 2 | `scripts/build_search_data.py`      | OCR + augment lookup                                 | `web/public/data/pages.json`                      |
| 3 | `scripts/build_embed_data.py`       | embed root                                           | `web/public/data/{embeddings.bin,embed_index.json}` (float16) |
| 4 | `scripts/build_atlas_layout.py`     | embed root (float32) **or** deployed payload (float16) | `web/public/data/atlas-layout.json`               |
| 5 | `scripts/build_novelty_data.py`     | embed root + reference index                         | `web/public/data/novelty.json`                    |
| 6 | `cd web && npm run build`           | all of the above                                     | `web/dist/` (Cloudflare Workers static assets)    |

`build_atlas_layout.py` prefers the native float32 `vectors.bin` because
UMAP is sensitive to the float16 → float32 round-trip (the deployed
fallback gets you a *near* layout, not an identical one). When the NAS
isn't mounted (CI / clean clones), pass `--from-published web/public/data/`
to read the deployed float16 payload — accept the small precision delta
versus refusing to build.

**Order matters.** A fresh `pursue embed run` invalidates 2–5;
re-deploying the site without re-running them ships dotted UMAP coords
pointing at deduped rows that are gone from `pages.json`. `random_state=42`
keeps the atlas layout reproducible across machines, so re-runs of step
4 against the same `vectors.bin` produce identical bytes.

## Worker dispatch (Cloudflare)

`worker/index.js` handles an explicit allowlist of `/api/*` paths
(`/api/retrieve`, `/api/chat`); everything else under `/api/*`, including
the static docs page at `/api/` (`web/src/pages/api.astro`) and any future
static `/api/*` pages, falls through to the ASSETS binding. Adding a new
dynamic route requires updating `WORKER_API_PATHS` in `worker/index.js`
*and* documenting it on `api.astro`. Adding a new static `/api/*` page
requires no Worker change. Method gating (e.g., 405 on non-POST) is the
handler's responsibility, not the dispatcher's — the allowlist is
path-only by design.
