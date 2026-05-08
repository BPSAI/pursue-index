# Current State

> Last updated: 2026-05-08

## Active Plan

**Plan:** Pipeline through OCR; static UI shipped to GitHub Pages; Surya GPU + LLM-fallback OCR ready; embed scaffold landed.
**Status:** scrape ✅ download ✅ ocr (tesseract + surya + llm-fallback + auto-mode) ✅ ui ✅ embed (scaffold) 🔧 — index/serve still stub.
**Current Sprint:** Wrap-up; backlog full Voyage embed run + benchmark harness + chat interface.

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
- [x] **`pursue embed` stage scaffold** — Voyage-3 default, OpenAI stub seam, idempotent against `(card_id, page, model_id, text_sha)`. CLI + settings + web build helper. 50/50 unit tests green. Live smoke against the 4153-page corpus with a fake embedder confirmed shape + idempotency; full Voyage run pending `VOYAGE_API_KEY` export (~$0.13 estimated).
- [x] **OCR LLM fallback + auto mode** — `ocr/llm.py` adds an Anthropic-vision engine matching the existing `(image)→(text,conf)` seam; system prompt sent with `cache_control=ephemeral`; per-image SHA-256 → response cached to disk; per-call token usage logged via `ocr.llm.usage`. `engine="auto"` runs primary (surya|tesseract) per page, re-OCRs pages with conf < `PURSUE_OCR_LLM_THRESHOLD` (default 70) via the LLM. Auto-mode rows preserve the primary attempt as a sibling `primary` block; `meta.json` records `engine: "auto:{primary}+{fallback}"`. New `pursue ocr run --force` bypasses the idempotency check. Surya now passes `math_mode=False` (no more `<b>...</b>` markup). 14 new tests (9 LLM + 5 auto-mode); 48/50 total green (2 pre-existing embed CLI failures unrelated). Live smoke on 15-page FBI HQ-83894 serial 220 with `claude-haiku-4-5`: 9 low-conf pages re-OCR'd, ~16k input + 3.1k output tokens (~$0.03 at Haiku rates), dramatic quality lift (page 1 went from 4 lines of garbage to a complete cover-sheet transcription).

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

### Session: 2026-05-08 — OCR LLM fallback + auto mode + small chores

- Added `src/pursue_index/ocr/llm.py` — Anthropic-vision OCR engine
  exposing `ocr_image(img) -> (text, conf)` matching the existing seam.
  System prompt is sent with `cache_control={"type": "ephemeral"}` so
  static instructions hit the cache-read rate after the first call.
  Per-image SHA-256 → response is cached to
  `{data_root}/ocr/.llm-cache/{sha}.json` so re-runs are free. Token
  usage logged via `ocr.llm.usage` on every call (input, output, cache
  read/creation). Provider routing scaffolded: Anthropic is v1, OpenAI
  is a stub raising `NotImplementedError`. Page images downscaled to
  1568px longest edge before encoding (Anthropic's 5MB hard limit on
  base64-encoded image inputs).
- Wired `engine="auto"` in `ocr/pipeline.py`: primary engine (Surya if
  `[gpu]` extras installed, else Tesseract; explicit `primary_engine`
  kwarg overrides) runs per page, re-OCR'd via the LLM whenever
  `confidence < settings.ocr_llm_threshold` (default 70). Auto-mode
  rows in `pages.jsonl` keep the LLM result as the top-level
  `text`/`confidence`/`engine`, with the primary attempt preserved as
  a sibling `primary` block for transparency. `meta.json.engine` is
  now `"auto:{primary}+{fallback}"` so the audit trail shows what
  actually ran.
- Added `pursue ocr run --force`: bypasses the `_is_done` idempotency
  check so a card with existing OCR output can be re-processed. Wired
  end-to-end through `ocr_card` and `ocr_all`.
- Disabled Surya's `math_mode` (default `True` injects `<b>...</b>`
  around inferred bold runs; the corpus has no math, downstream search
  would otherwise have to strip the markup).
- Web 404 page: switched hardcoded `<a href="/">` to
  `import.meta.env.BASE_URL` so it survives a future `base` config
  change (tracked from the surya plan's open-follow-ups).
- New `[llm]` optional extra in `pyproject.toml` pinning
  `anthropic>=0.40`. Default install stays Tesseract-only.
- New env vars (`.env.example` updated, retired `AZURE_DI_*`):
  `PURSUE_OCR_LLM_PROVIDER` (anthropic|openai),
  `PURSUE_OCR_LLM_MODEL` (default `claude-sonnet-4-6`),
  `PURSUE_OCR_LLM_THRESHOLD` (default 70).
- 14 new tests (9 LLM + 5 auto-mode); 48/50 unit tests pass (the 2
  failures are pre-existing in `test_embed_cli.py`, not touched by
  this work).
- Architecture: extracted `ocr/auto.py` (auto-mode helpers, no I/O)
  and `ocr/runners.py` (per-engine page-streaming loops) to keep
  `pipeline.py` under the function-count limit. arch-check returns
  warnings only (file sizes >200 lines, all <300; threshold 400 err).
- Live smoke on FBI HQ-83894 serial 220 (15-page faded scan,
  Tesseract baseline mean conf 70%): auto mode triggered LLM
  fallback on 9 pages (the ones below 70% conf), kept tesseract for
  the 6 clean pages. 16,453 input + 3,115 output tokens across the
  9 calls = ~$0.03 at Haiku-4.5 prices (~$0.10 projected at
  Sonnet-4.6). Quality lift is dramatic — page 1 went from 4 lines
  of broken glyphs to a clean transcription of the FBI cover sheet
  with case numbers, FOIPA stamp, redaction marker, and barcode.
  Smoke used haiku to avoid Claude Max sonnet rate-limit; production
  default remains `claude-sonnet-4-6`.
- Commits on `worktree-agent-a8f8c3bb83823541f`: `f68d368` (llm
  engine), `2d79b54` (auto + force), `4d31810` (surya math_mode),
  `bb7c021` (web 404), `caf720f` ([llm] extra + env.example),
  `9b8029e` (image resize fix from smoke).

### Session: 2026-05-08 — `pursue embed` stage scaffolded

- Added `src/pursue_index/embed/` module: `pipeline.py` (orchestration),
  `voyage.py` (Voyage-3 adapter — default per the embed-stage plan),
  `openai.py` (stub seam for v2 A/B testing), `store.py` (on-disk
  format helpers).
- Output convention matches the plan:
  `{data_root}/embeddings/{model_id}/{vectors.bin, index.json}` —
  contiguous float32 [N, D] little-endian binary; index records
  `{card_id, page, text_sha, offset}` per row.
- Idempotency keyed by `(card_id, page, model_id, text_sha)`; running
  on an unchanged corpus is a `embed.run.noop`. A corrected page
  (text_sha changes) re-embeds only that page.
- `pursue embed run --manifest …` CLI added with `--limit`,
  `--cost-cap-usd`, `--batch-size`, `--provider`, `--model` flags.
  Lazy-imports the pipeline so install-without-`[embed]` still loads
  the CLI.
- Cost guardrail: $1 default cap from estimated tokens (chars / 4 ≈
  tokens, $0.06 / 1M Voyage pricing); aborts before any API call when
  exceeded; `--cost-cap-usd N` overrides.
- `scripts/build_embed_data.py` reads the embed output and writes the
  web payload: float16 `embeddings.bin` + compact `embed_index.json`
  (`pages: [[card_id, page]]`). Logs a warning when binary > 10 MB so
  we know when to flip to server-side retrieval (chat-interface plan).
- Live smoke (no VOYAGE_API_KEY available): used `scripts/smoke_embed_fake.py`
  with a deterministic 8-dim fake embedder against the real 4153-page
  NAS corpus.
  - First run: 4153 embedded, 0 skipped, 116 cards seen, 0.4s,
    vectors.bin = 132,896 B (= 4153 × 8 × 4).
  - Second run: 0 embedded, 4153 skipped — full no-op as designed.
  - Web build: `embeddings.bin` 66 KB float16 + `embed_index.json`
    109 KB; payload well under the 10 MB threshold (real Voyage-3 at
    1024 dims would be ~8.5 MB binary — still under).
- Settings: `PURSUE_EMBED_PROVIDER` (voyage|openai), `PURSUE_EMBED_MODEL`
  (default voyage-3), derived `embeddings_dir` property.
- 10 new unit tests; 50/50 unit tests green; arch clean on every
  modified file.
- Commits on this worktree branch (not pushed):
  `feat(embed): pipeline scaffold + Voyage adapter`,
  `feat(embed): wire pursue embed run CLI + settings`,
  `feat(embed): web build helper + [embed] extra`,
  `chore(embed): add fake-embedder smoke script`.
- Open: full Voyage-3 embed run is gated on a `VOYAGE_API_KEY` being
  exported in the workstation env; estimated cost is $0.13 per the
  plan and the $1 cap leaves plenty of headroom.

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

1. **Full Voyage-3 embed run** — export `VOYAGE_API_KEY` and run
   `pursue embed run --manifest data/manifests/latest.json` against the
   full 4153-page corpus. Estimated $0.13 (per the embed-stage plan)
   and well under the $1 cap. Then run `python scripts/build_embed_data.py`
   to produce the web payload (~8.5 MB float16 binary at 1024 dims).
2. **Full Surya re-OCR with auto-mode** — `pursue ocr run --force
   --engine auto --manifest data/manifests/latest.json` now possible
   with the `--force` flag landed. Auto-mode will run Surya as primary
   (since `[gpu]` is installed), LLM-fallback the low-conf pages.
   Need `ANTHROPIC_API_KEY` exported in workstation env. Estimated
   cost: ~$0.10/card with Sonnet 4.6 on the worst FBI scans, near
   zero on clean typewriter docs (most pages won't trigger fallback).
3. **OCR benchmark harness** (`ocr-benchmark.md`) — now unblocked by
   the `--force` flag. A/B Tesseract vs Surya vs Surya+LLM on the 5
   representative golden PDFs, produce mean-confidence + wall-clock
   + cost numbers for the methodology page.
4. **Chat interface** (`chat-interface.md`) — RAG worker over the embed
   payload, streaming citations from Anthropic.
5. **Index stage** — wire SQLAlchemy models (cards, pages) into the
   manifest + OCR output. Becomes useful when the corpus outgrows
   ~10 MB of in-browser JSON.
6. **FastAPI service** — only after Postgres ingest exists.

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
