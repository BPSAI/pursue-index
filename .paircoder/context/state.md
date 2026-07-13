# Current State

> Last updated: 2026-07-13 (doc-hygiene pass — state.md rebuilt, plans/ tidied,
> residual engine/stat staleness fixed). Engine-identity correction pass is
> merged to `main` (commit `1fb853f`), not staged.
>
> Session/sprint history before 2026-07-13 lives verbatim in
> [`state-archive-2026H1.md`](./state-archive-2026H1.md).

---

## Current status (2026-07-13)

Public site live at <https://pursueindex.com> (Cloudflare Workers + Static
Assets). Repo is public: `BPSAI/pursue-index`, Apache-2.0. **v1.5.0 shipped.**

**Corpus / releases**
- **Release 4 ingested and live — 334 cards.** 8 curated `/finds` entries live.
- **A/V self-served from our R2** (116 A/V cards). DVIDS is the cited provenance
  source, **not** the playback path — the old DVIDS iframe/embed is retired.
- **11 NASA audio (AUD) cards transcribed** via AssemblyAI and searchable
  (transcript corpus integrated into retrieval).
- **PDF r2-mirror gap closed** — `storage mirror-pdfs` / `verify-mirror` land
  PDFs into the R2 mirror as part of the ship path.

**OCR engine — `llm-dots`**
- Claude **Sonnet 4.6** vision per page (primary) + local **dots.mocr** as the
  content-filter (HTTP 400) backstop. Concurrency **8**.
- **Retired (do not use): `tesseract`, `surya`, `auto`, old "Haiku fallback".**
- AUD cards transcribe via **AssemblyAI**, not the page-OCR engine.

**Vision augmentation**
- **alex-zhang42 augment corpus RETIRED.** Replaced by our own **Opus-4.8
  image-observations** vision pass over residual image-only pages.
  `--augment-from` is stripped from `pursue embed run`; orphan augmented rows
  dropped and vectors re-exported (commits `cf58ecc`, `b3c3505`, `754ee26`).

**Turnkey release ("never-again")**
- `/ship-tranche` slash command + `preflight_ocr` guard + `storage contract`
  (`pursue storage verify`) + poll auto-surface deployed (commits `669961a`,
  `1e31aed`, `a4da0cd`, `b5d3abb`). Verify-engine/model-before-spend enforced.
- **clean-qc** LLM-judge QC stage (run in pursue-curate over freshly-OCR'd
  pages before embed/publish); web bundle refreshed to **v3 — 136 cards**.

**Deferred**
- **Sonnet 5 OCR migration** — deferred pending a benchmark.

## Pipeline

```
scrape → download → ocr → clean-qc → embed → serve   (+ chat, novelty, atlas)
```
AUD cards branch off `ocr` into the AssemblyAI transcription path. Each stage
is independently runnable via the `pursue` CLI and idempotent against the
content-hashed manifest (`card_id = sha256(asset_url || title)[:16]`).

## What's Next

### Active
- _Nothing in flight._ R4 shipped and live; turnkey ship path deployed.

### Open work (this repo, ranked)
- **P1 — plans/ housekeeping follow-through.** Shipped/superseded plans archived
  under `.paircoder/plans/archive/`; tranche-diff run artifacts moved to
  `data/tranche-diffs/`. (Done in this pass — see below.)
- **P2 — Black Vault reference corpus** (`plans/black-vault-reference.md`).
  Novelty detection still runs on the 10-passage synthetic placeholder; replace
  with a real FOIA prior-disclosure archive. Refresh the plan's Surya-era cost
  model first (engine is now llm-dots).
- **P2 — Incidents map clustering** (`plans/incidents-map-clustering.md`).
  Geographic density visualization; never built. Depends on display-date
  phase-4 for era-slicing.
- **P2 — Display-date phase 4** (`plans/display-date-curation.md`). Operator
  review of ~156 agent-proposed display dates (~45-75 min). Phases 1-3 shipped;
  `/timeline` is live. Unblocks the map's era-slicing.
- **P2 — `/altered` facts-only rebuild.** The old per-card OCR-diff surface was
  retired (v1.2.2); a facts-only byte-history listing is the correctly-scoped
  successor. Check the orphan `web/src/pages/altered/[card_id].astro` still on
  disk. (See archive entry 2026-05-27 v1.2.6.)

### Operator / flagged
- **`src/pursue_index/index/models.py:84`** — the optional forensic-ingest
  Postgres `cards.ocr_engine` column still defaults to `"tesseract"`. Off the
  deployed read path; changing it is a schema-default/migration decision left
  for the operator.

## Known dark code

None. All shipped features are wired, validated, and live.

## Build and Deploy

- **Primary:** Cloudflare Workers Builds (dashboard-configured). Triggers on
  push to `main`. Build: `cd web && npm install && npm run build`.
  Deploy: `npx wrangler deploy`.
- **Manual fallback:** `.github/workflows/deploy-cf.yml` runs the same chain on
  `workflow_dispatch`.
- **Local:** `npx wrangler deploy` from a clean checkout (needs
  `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`, or `wrangler login`).

## Quick Commands

```bash
# Pipeline (idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine llm-dots
pursue embed run --manifest data/manifests/latest.json

# Storage contract (R2 mirror + serving pointers)
pursue storage verify
pursue storage mirror-pdfs

# Tests
pytest -x                      # python
npm --prefix worker test       # worker
cd web && npm run build        # web

# Dev
cd web && npm run dev          # web, localhost:4321
npx wrangler dev               # worker, against real KV + secrets
```

## Blockers

None.
