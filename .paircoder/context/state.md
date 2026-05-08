# Current State

> Last updated: 2026-05-08

## Active Plan

**Plan:** Pipeline through OCR; static UI shipped to GitHub Pages.
**Status:** scrape ✅ download ✅ ocr ✅ ui ✅ — index/serve still stub.
**Current Sprint:** Wrap-up; backlog Surya GPU OCR + LLM fallback + index ingest.

## Current Focus

The CSV pivot is in (`485748f` on `origin/main`). `pursue scrape run` fetches
via curl_cffi with Chrome TLS impersonation and writes a 161-card manifest
(119 PDF / 28 VID / 14 IMG, sha256 `596cc1881aa97d2f…`). 13/13 unit tests pass.

Next step is to run `pursue download run` against the manifest and start
filling out the OCR + ingest + serve stubs.

## Task Status

### Active Sprint

- [x] Apply CSV-pivot patch (extractor → csv_fetcher; manifests_dir split)
- [x] Diagnose 403 — Akamai bot detection on TLS fingerprint
- [x] Switch fetcher to `curl_cffi` with `impersonate="chrome"`; add regression test pinning the contract
- [x] Clean up `.env` — drop stale Playwright vars, set `PURSUE_SCRAPE_USER_AGENT=` empty
- [x] Run `pursue scrape run` end-to-end; manifest written + raw CSV archived to NAS
- [x] Squashed commit + push to `origin/main` (`485748f`)
- [x] `pursue download run` — 133/161 assets on NAS (116 unique PDFs + 14 images; 28 videos off; 3 PDF cards de-duped against paired entries). Required a follow-up fix re-exporting `asset_path_for` (`9debf96`).
- [x] OCR v1 — Tesseract-only, idempotent. `ocr_card` writes `pages.jsonl` + `meta.json` per architecture spec. Smoke-tested on Apollo 17 debriefing PDF (2 pages, 3.9s).
- [x] OCR full run — 116 cards / 4,153 pages, 0 failures, ~64 min wall-clock at 4-way concurrency on the workstation.
- [x] Static UI scaffold (`/web`) — Astro + Preact + Tailwind v4 + MiniSearch. Routes: /, /card/[id], /search, /diff. Auto-deploys to GitHub Pages on push.
- [x] Search index — `pages.json` (5.3 MB) shipped; full-text MiniSearch live across all 4,153 OCR'd pages.

### Phase 2 backlog (sequenced)

See `.paircoder/plans/phase-2-roadmap.md` for the master plan.
Target: pursueindex.com / pursueindex.ai public launch with chat.

1. `ocr-gpu-surya.md` — Surya on 5090 for speed + quality
2. `ocr-llm-fallback.md` — LLM fallback for low-confidence pages
3. `ocr-benchmark.md` — A/B harness, golden set, methodology numbers
4. `review-correct.md` — agent-driven + human review queue, corrections
5. `embed-stage.md` — `pursue embed` stage, Voyage-3 vectors
6. `ui-redesign-alien.md` — declassified-terminal aesthetic (parallel)
7. `chat-interface.md` — RAG chat with citations, edge backend
8. `production-launch.md` — DNS, rate limits, methodology page, HN post

### Deferred / out of phase 2

- Postgres `index` + FastAPI `serve` (in-browser retrieval suffices at this corpus size)
- DVIDS video ingestion (phase 3)
- Multi-tranche analytics (until Release 02 lands)

## What Was Just Done

### Session: 2026-05-08 — CSV pivot shipped end-to-end

- Reviewed the `pursue-index-csv-pivot.tar.gz` patch (v0.1.0 → v0.2.0):
  Playwright extractor + runner removed; `csv_fetcher.py` + `normalize.py`
  added; storage split (`PURSUE_DATA_ROOT` vs `PURSUE_MANIFESTS_DIR`);
  models, downloader, CLI updated to the new asset_* shape.
- Diagnosed the 403: Akamai TLS-fingerprint bot detection. Plain httpx is
  blocked even with full Chrome client-hint headers; curl_cffi's
  `impersonate="chrome"` clears the gate.
- TDD: wrote `tests/unit/test_csv_fetcher.py` first — failed on missing
  `_http_get` seam, then went green after rewriting the fetcher.
- Pinned `curl-cffi>=0.7` in `pyproject.toml`; cleaned local `.env`.
- 13/13 unit tests green; arch check clean on every modified file.
- Live `pursue scrape run` produced the 161-card manifest committed at
  `data/manifests/latest.json` (csv_sha256
  `596cc1881aa97d2fa49a45edab14d60802616e73ce125d286120e00d967cafa2`).
- Bundled paircoder + Claude Code integration into the same commit per
  user direction.
- Squashed commit `485748f` pushed to `origin/main`.

## What's Next

1. **Index stage** — wire SQLAlchemy models (cards, pages) into the manifest +
   OCR output. The static UI gives us in-browser search already; Postgres
   becomes useful when the corpus outgrows ~10 MB of in-browser JSON.
2. **GPU OCR via Surya** (`.paircoder/plans/ocr-gpu-surya.md`) — likely 5–20×
   speedup vs Tesseract on the long FBI scans, plus better quality.
3. **LLM OCR fallback** (`.paircoder/plans/ocr-llm-fallback.md`) — replaces
   the original Azure DI plan with frontier vision models.
4. **FastAPI service** — only after Postgres ingest exists; for now the
   static UI covers all interactive needs.

## Blockers

None.

## Quick Commands

```bash
# Status
bpsai-pair status

# Tests
pytest -x

# Pipeline
pursue scrape run                                # writes data/manifests/latest.json
pursue download run --manifest data/manifests/latest.json
```
