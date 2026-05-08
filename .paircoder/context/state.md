# Current State

> Last updated: 2026-05-08

## Active Plan

**Plan:** Pipeline through OCR; static UI shipped to GitHub Pages; Surya GPU engine ready.
**Status:** scrape ✅ download ✅ ocr (tesseract + surya) ✅ ui ✅ — index/serve still stub.
**Current Sprint:** Wrap-up; backlog LLM fallback + benchmark harness + index ingest.

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
- [x] **Surya GPU OCR engine** — `ocr/surya.py` adapter slots into the existing engine seam; `ocr_card`/`ocr_all`/`pursue ocr run --engine surya` route by engine name; `pages.jsonl` + `meta.json` record `"engine": "surya"`. `surya-ocr>=0.17` added under `pyproject.toml [gpu]` extra. Live smoke: 40-page FBI HQ-83894 ran in 56.76s @ 93.90% mean conf vs Tesseract's 106.19s on the same file.

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

### Session: 2026-05-08 — Surya GPU OCR engine landed

- Added `src/pursue_index/ocr/surya.py` — lazy-loaded `RecognitionPredictor`
  + `DetectionPredictor` cached as module singletons. `ocr_image(img)`
  returns `(text, conf_0_to_100)` matching the Tesseract path's shape.
  Per-line confidences scaled 0..1 → 0..100.
- Added engine routing in `ocr/pipeline.py`: new `engine` kwarg on
  `_run_engine` / `ocr_card` / `ocr_all`. `pages.jsonl` and `meta.json`
  now record whichever engine ran. Default still tesseract; surya runs
  serialized (1 card at a time) since it's GPU-bound.
- Extended `Settings.ocr_engine` Literal to include `"surya"`; CLI
  `pursue ocr run` accepts `--engine`.
- Added `[gpu]` extra in `pyproject.toml` pinning `surya-ocr>=0.17`.
- 23/23 unit tests green; arch clean on all modified files.
- Live smoke (worktree branch, transformers downgraded to 4.x for
  surya 0.17 compat — this needs to land in the venv before others run
  the engine):
  - Apollo 17 D6 (2 pp): 7.87s wall, mean conf 88.95
    (Tesseract baseline: 3.91s — model load dominates short docs)
  - FBI HQ-83894 serial 438 (40 pp, 14 MB): 56.76s wall, mean conf 93.90
    (Tesseract baseline: 106.19s — ~1.87x faster end-to-end on a
    document type the plan called out as Tesseract-weak)
- Commits on `worktree-agent-a2f3ae5d55644d8b4` branch (not pushed):
  `41ef7b1` (engine + tests), `f521f93` (det predictor wiring).

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

1. **Full Surya re-OCR** — once the worktree merges, run
   `PURSUE_OCR_ENGINE=surya pursue ocr run --manifest …` against all
   116 PDFs. Existing tesseract output will be skipped by the
   idempotency check; need a `--force` flag (or to wipe `meta.json`)
   to actually re-OCR. Out of scope for this worktree.
2. **OCR benchmark harness** (`ocr-benchmark.md`) — A/B Surya vs
   Tesseract on the 5 representative golden PDFs called out in the
   plan, produce mean-confidence + wall-clock numbers for the
   methodology page.
3. **LLM OCR fallback** (`ocr-llm-fallback.md`) — vision-model cleanup
   pass for pages where Surya confidence is low.
4. **Index stage** — wire SQLAlchemy models (cards, pages) into the
   manifest + OCR output. Becomes useful when the corpus outgrows
   ~10 MB of in-browser JSON.
5. **FastAPI service** — only after Postgres ingest exists.

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
