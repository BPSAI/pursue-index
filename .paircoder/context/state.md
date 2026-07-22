# Current State

<!-- paircoder:state:begin -->
## Active Plan

**Plan:** Orchestrated from opsec — `pursue-opsec-staging/plans/backlogs/BACKLOG.md`
**Status:** Launch push (research-preview → launch); Launch Sprint 1 in progress

## What Was Just Done

- Launch Sprint 1 hygiene: stale site-copy purge, comment-path hygiene, plan-doc consolidation to opsec.

## What's Next

1. Fleet backlog: `pursue-opsec-staging/plans/backlogs/BACKLOG.md` (this repo's items are tiered there).

## Blockers

None
<!-- paircoder:state:end -->

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
- **Release 4 ingested and live — 334 cards.** 37 curated `/finds` entries live.
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

**Forward planning is orchestrated from opsec.** All open work for this repo is
tracked (tiered, prioritized) in the master fleet backlog:
`~/projects/pursue/pursue-opsec-staging/plans/backlogs/BACKLOG.md`. Do not
maintain a separate ranked backlog here — it drifts.

Detailed technical plans for this repo's open items live in opsec under
`plans/specs/` (consolidated with the backlog) and are linked from `BACKLOG.md`:
- `plans/specs/black-vault-reference.md` — novelty reference corpus (T1.1)
- `plans/specs/display-date-curation.md` — display-date phase 4 (T3.2)
- `plans/specs/incidents-map-clustering.md` — `/map` surface (T3.3)

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
