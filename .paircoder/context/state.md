# Current State

> Last updated: 2026-05-09 (post-launch — public site live, full pipeline shipped)

## Current Focus

**Public launch is done.** Site is live at <https://pursueindex.com> on
Cloudflare Workers + Static Assets. Full pipeline (scrape → download →
OCR → embed → serve) shipped and re-runnable. Chat interface live with
citation discipline and abstention behavior. Repo is public on GitHub
(`BPSAI/pursue-index`, Apache-2.0) with `existing_users` interaction
limits through 2026-11-09.

A parallel project (`alex-zhang42/ufo-pursue-open-atlas`) released
hours later with a different angle: VLM-described image content, CC0
dataset on HuggingFace + 3D atlas. Crediting it on /methodology under
Related Work; ingest of their image-description blocks into our
retrieval is on the post-launch backlog (see `What's Next`).

## Active Plan

| Stage     | Status   | Output                                                             |
|-----------|----------|--------------------------------------------------------------------|
| scrape    | shipped  | curl_cffi + Chrome TLS, 161-card manifest, hash-pinned             |
| download  | shipped  | 116 PDFs + 14 images on NAS via content-addressable layout         |
| ocr       | shipped  | 3,529 Surya pages + 624 LLM-cleaned pages (auto-mode), 4,153 total |
| embed     | shipped  | Voyage-3 1024d float16, ~8 MB in-browser payload                   |
| serve     | shipped  | Astro static + CF Worker (CORS-locked, 5/IP/24h, $100/day cap)     |
| chat      | shipped  | RAG with mandatory citations, anonymous + BYOK tiers               |
| novelty   | shipped  | machinery + UI; placeholder reference corpus (10 passages)         |
| atlas     | shipped  | 2D UMAP semantic browser (/atlas) — regl-scatterplot, 4,119 dots   |

## What Was Just Done

### Session: 2026-05-09 — Semantic-browser PR #6 review-fixes (branch `feat/semantic-browser`)

Addressed all legitimate findings from the four-reviewer pass on PR #6
(vaivora REQUEST_CHANGES, nayru APPROVE_WITH_NITS, laverna SEC review,
Codex auto-review):

- **vaivora P0 + nayru #7 (deep-link contract):** Atlas click handler
  and mobile fallback list both now emit fragment-only URLs via a new
  `buildCardHref` helper (`/card/<id>#page-N`). The query slot is
  reserved for `?q=…` (Cite.astro / SearchIsland highlight carry-through);
  squatting on `?page=N` was unread by `CardOcrIsland` and conflicted with
  the established pattern.
- **vaivora P1 (search-relevance divergence):** Replaced the naive
  substring filter (`filterIndicesByQuery`) with a MiniSearch index built
  from the same fields + boost / prefix / fuzzy config that powers
  `/search`. Same input, same matches across both surfaces. Added
  `buildAtlasMiniSearch` + `searchIndicesViaMiniSearch` helpers.
- **nayru #3 (float16-vs-float32 layout drift):** Regenerated
  `web/public/data/atlas-layout.json` from the native float32
  `vectors.bin` on the NAS. New sha (`0f3484a77549c623`) differs from
  the float16-derived deploy (`81628da1bca86858`).
- **nayru #4 (non-atomic JSON write):** `_write_layout` now writes to a
  `.tmp` sibling then `os.replace` — POSIX-atomic on the same fs, so a
  crash mid-write can't leave the 343 KB asset half-written. Two new
  tests pin the contract (atomic-no-tmp-leftover + replace-failure
  preserves existing).
- **nayru #5 (search redraw not debounced):** `query` now feeds a
  `debouncedQuery` at 150ms; the 4,119-row regl-scatterplot upload only
  re-runs after the user stops typing, not per keystroke.
- **nayru #6 (mobile flash <400px):** Width state starts at 0
  (unknown); resize effect measures real viewport on mount; render is
  held in the loading state until `width > 0`. Real <400px viewports no
  longer transiently mount the canvas before the resize handler corrects.
- **nayru #8 (eager hydration):** `atlas.astro` switched from
  `client:load` to `client:visible` — defers the ~7 MB `pages.json` +
  340 KB `atlas-layout.json` parallel fetch to when the canvas
  scrolls into view.
- **nayru #9 (identity-map noise):** Dropped the `categoryColors().map(...)`
  no-op in the regl init.
- **laverna SEC-001 (semver-floating regl-scatterplot):** Pinned to
  exact `1.16.0` in `web/package.json`. Added `.github/dependabot.yml`
  covering npm (web/), pip (root), and github-actions ecosystems with
  weekly cadence.
- **laverna SEC-003 (defensive URL encoding):** `buildCardHref` runs
  `encodeURIComponent` on `cardId` — no-op for today's hex IDs but
  hardens any future flow that surfaces user-supplied tokens through
  the same helper.
- **Codex P2 #1 (regl resize):** Added an effect that calls
  `scatterplot.set({ width, height })` on viewport-width change so the
  WebGL canvas stays in sync with CSS dimensions after a desktop resize.
- **Codex P2 #2 (mobile filter regression):** `ClusterListFallback`
  now accepts `atlasIndex` + `query` and filters cluster contents to
  matched indices — the search input on phones now actually filters.
- **vaivora latents (docs / orchestration):** New `## Web build chain
  (post-embed)` section in `docs/architecture.md` documents the
  `embed → search/embed/atlas/novelty → web build` order; clarifies
  that `build_atlas_layout.py` reads native float32 by default with a
  float16 published-payload fallback. README's `## What's live` and
  state.md's `## Active Plan` table now include `/atlas`.

Tests: 8/8 python (was 6) — two new tests on `_write_layout` atomicity.
13/13 TS — three new tests covering `buildCardHref` (hash-only +
encoding) and `buildAtlasMiniSearch` / `searchIndicesViaMiniSearch`
(stemming + empty-query parity). Web build clean (168 pages). Arch
check zero errors on every modified file. The semantic-browser plan at
`.paircoder/plans/semantic-browser.md` is retired pending operator
delete-on-merge per the doc-cleanup pattern.

### Session: 2026-05-09 — alex-zhang42 ingest review-fixes (PR #2 follow-up, branch `feat/alex-zhang-ingest`)

Addressed the union of actionable findings from three parallel reviews
(vaivora REQUEST_CHANGES, laverna + nayru APPROVE_WITH_NITS):

- **vaivora #1 (build_search_data drops augmentation):** Rewrote the
  script to detect `augmented_by` in `embeddings/{model}/index.json`,
  mirror the embed pipeline's `atlas_join` lookup, and apply the same
  `_augment_text` to each matched page before writing `pages.json`.
  New `--augment-from` flag (required when index declares augmentation;
  refuses to ship out-of-sync payload).
- **vaivora #2 (provenance died at build_embed_data):** `_write_index`
  now copies `augmented_by` from the source index into the deployed
  `embed_index.json`. End-to-end provenance.
- **vaivora #3 (orphan-row drift):** `IndexRow` gained an `augmented`
  flag (omitted on disk when False, backward-compatible). Pipeline
  marks new rows with `augmented=True` iff `(card_id, page)` was in
  the lookup. `build_embed_data._dedupe_rows` drops un-augmented rows
  whose `(card_id, page)` has an augmented sibling. Vector file is
  filtered in lockstep.
- **SEC-001 (sha256 sidecar unverified):** `load_atlas_index` now
  hashes the corpus and compares against `<stem>.sha256` before
  parsing. Hard fail on mismatch or missing sidecar; opt-out via
  `PURSUE_AUGMENT_SKIP_HASH_CHECK=1` for local regeneration.
- **SEC-002 (1.0 threshold disabled the gate):** `--augment-miss-rate-threshold`
  clamped to `[0.0, 0.5]` at both Typer (`min=`/`max=`) and call-site
  (`_validate_threshold`).
- **SEC-003 (HF HEAD drift silent):** `build_alex_zhang_corpus.py`
  hardcodes `PINNED_REVISION = "b0f0c79924b88d339846aa9fc4283958fe15682b"`
  and aborts when upstream HEAD differs.
- **nayru P1 (provenance half-truth):** `_load_augment_provenance`
  raises (FileNotFoundError / ValueError) on missing or empty
  `.revision` / `.sha256` sidecars rather than emitting `revision=""`
  into `index.json`.
- **nayru P1 (empty source_url silently missed):** `atlas_join` now
  raises `AtlasJoinError` on records with missing or empty `source_url`.

Tests: 116 python (was 95; +21 covering all the above). Worker: 56/56
green. Web build clean. Arch check: zero errors on every modified file
(file-too-large warnings only). Out of scope per task instructions:
docstring polish on canonicalize_url, SEC-004 (Jaime Maussan caption —
operator policy call), the `(license TBD)` line in cite.astro.

### Session: 2026-05-09 — alex-zhang42 VLM ingest (implementation, branch `feat/alex-zhang-ingest`)

- Pinned alex-zhang42/ufo-pursue-open-atlas at HF revision
  `b0f0c79924b88d339846aa9fc4283958fe15682b` (2026-05-08 release).
  Their `corpus.jsonl` form isn't actually shipped — only the parquet
  config — so wrote `scripts/build_alex_zhang_corpus.py` that
  deterministically projects `text/train.parquet` -> JSONL. Output
  committed at `data/external/alex-zhang42-corpus.jsonl` (14.6 MB) with
  `.sha256` and `.revision` sidecars.
- New module `src/pursue_index/embed/atlas_join.py` implements
  `load_atlas_index(corpus_jsonl, manifest)` -> `{(card_id, page): [tags]}`
  keyed by *our* `stable_card_id`. Direct hash match first; then a
  canonical-URL fallback (lowercase + percent-decode + collapse
  whitespace/underscore runs) to handle the war.gov-served literal-space
  filenames that we percent-encode and they slugify. Fails closed if
  miss-rate > 1% on the join. Real-corpus run: 1212 pages augmented
  across 79/161 cards, 1366 image-tag lines total — under threshold.
- Wired augmentation into `embed/store.py::_read_card_pages` (optional
  `augment_lookup` arg appends `[[IMAGE-DESCRIPTIONS via …]]` block
  before `text_sha`, so existing idempotency naturally re-keys augmented
  rows). `embed/pipeline.py::embed_run` accepts `augment_lookup` +
  `augmented_by` provenance; `write_index` now records the
  `augmented_by` block in `index.json`.
- New CLI flags on `pursue embed run`: `--augment-from PATH` and
  `--augment-miss-rate-threshold FLOAT`. Embed sub-app extracted to
  `src/pursue_index/cli/embed_cli.py` to keep `commands.py` under the
  per-file size cap.
- 16 new tests (atlas_join: 7, embed_augment: 7, embed_cli: 2) plus
  fixture `tests/fixtures/atlas_join_sample.jsonl`. Full suite: 95/95
  python, 56/56 worker. Web build clean (162 pages). Arch check
  errors: zero (warnings only on file-too-large, all under hard limit).
- Methodology (`web/src/pages/methodology.astro`) Related Work section
  extended with the augmented-retrieval paragraph + TODO marker for
  the post-run coverage stat. Cite (`web/src/pages/cite.astro`) gained
  a section on dual citation when quoting an `[[IMAGE-DESCRIPTIONS …]]`
  snippet.
- **Did NOT run** the augmented embed — operator approval required for
  the ~$0.13 Voyage spend.

### Session: 2026-05-09 — Post-launch cleanup

- **Polish patch (commit `82f6a2c`):** Removed dead splash/preview-gate
  machinery (web/src/pages/splash.astro, magic-link routes, cookie
  helpers, RFC-6265 cookie test). Fixed `RATE_LIMIT = 100` → `5`
  FIXME that should have been flipped at gate-flip but wasn't —
  20x quota exposure closed (daily $100 spend cap was already in
  place so worst-case bill was bounded). Added Related Work section
  to /methodology crediting alex-zhang42's parallel release. Tests:
  56 worker / 79 python green; 162-page build clean.
- **Doc cleanup:** Deleted 9 completed plans + post-launch artifacts
  (chat-interface, embed-stage, novelty-detection, ocr-benchmark,
  ocr-gpu-surya, ocr-llm-fallback, phase-2-roadmap, production-launch,
  ui-redesign-alien plans; launch-readiness/STATE.md;
  cloudflare-pages-migration runbook). README rewritten to reflect
  public-launch reality. project.md refreshed (pipeline diagram now
  shows actual `embed → serve` flow, tech stack lists shipped
  surface, license updated to Apache-2.0).

### Session: 2026-05-09 — Launch-readiness QC pass + gate flip

- Two real-user fixes pushed to prod (`815844b`):
    - /methodology License section now references Apache-2.0 with
      links to apache.org and /cite (was: "License: TBD before public
      launch")
    - CITE entry added to main nav between METHODOLOGY and SUPPORT
- Repo flipped public + GitHub interaction limits applied
  (`existing_users`, expires 2026-11-09).
- Divona QC sweep on prod: 19 scenarios across 5 critical/regression
  suites — smoke 4/4, chat 3/3 (4 read-only-skipped as designed),
  cite 4/4, mobile 3/3, support 5/5. Zero failures. GO issued.

### Session: 2026-05-09 — Novelty detection (machinery + UI)

- `pursue novelty compute` CLI + machinery: cosine top-1 vs reference
  index → card-level disclosure_status (novel / partial /
  previously-disclosed). Synthetic placeholder reference corpus
  (10 hand-crafted public-domain UFO-adjacent passages: Roswell 1947,
  Project Blue Book, Hottel memo, RB-47, Malmstrom, etc.).
- UI: index page DISCLOSURE filter chip; card detail page Provenance
  panel showing top-3 reference matches.
- Black Vault integration deferred to post-launch backlog.

For deeper history see `git log` — older sessions covered the CSV
pivot (Akamai bypass via curl_cffi), Surya GPU OCR engine landing,
LLM fallback + auto-mode, full corpus passes, OCR benchmark report,
embed stage, chat interface end-to-end, custom domains, security
hardening, git history scrub.

## What's Next

### Immediate (launch comms — operator-driven)

1. Watch HN for dang's response on the flagged Show HN. The retitled
   post was submitted with the email already sent.
2. Reddit r/UFOs + r/DataHoarder — monitor comments, respond to
   genuine technical questions. Add cross-link to alex-zhang42's
   project on the r/DataHoarder thread (highest-leverage cross-credit
   move).
3. The War Zone email — wait for response (1-3 day cycle).

### Post-launch backlog (priority order)

1. **Ingest alex-zhang42 VLM image descriptions** — implementation
   landed on `feat/alex-zhang-ingest`. Outstanding step: operator runs
   `pursue embed run --manifest data/manifests/latest.json --augment-from
   data/external/alex-zhang42-corpus.jsonl` (~$0.13, ~5 min) once they
   want to spend the Voyage tokens, then republishes
   `web/public/data/embeddings.bin` + `index.json` and updates the
   coverage-stat TODO in `methodology.astro`.
2. **Curated Finds expansion** — current set is intentionally small to
   set the editorial bar. Plan: `.paircoder/plans/curated-finds.md`.
3. **Auto-mode full corpus re-OCR** — Surya-primary + LLM-fallback
   re-run on every page (~8% will trigger LLM cleanup, ~$1.36 at
   Haiku rates). Quality lift is real but incremental over what's
   shipped. Needs operator attendance for the run.
4. **Auto-poll for new tranches** — DOW publishes new releases by
   updating the same CSV in place. Polling closes the gap. Plan:
   `.paircoder/plans/auto-poll-tranches.md`.
5. **Review-and-correct pipeline** — accept community OCR corrections
   via GitHub issues; flow them back into the index. Plan:
   `.paircoder/plans/review-correct.md`.
6. **Black Vault reference corpus** — acquire + OCR + embed the
   canonical FOIA archive (~100k–500k pages) so novelty detection
   moves from "methodology demo" to "real coverage measurement"
   for every card.

### Optional cleanup

- Delete the local `pre-scrub-backup-*` git tag once you're confident
  the history scrub stuck.

## Blockers

None.

## Quick Commands

```bash
# Pipeline (re-runnable, idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json

# Tests
pytest -x                     # python, 79 tests
npm --prefix worker test      # worker, 56 tests
cd web && npm run build       # web, 162 pages

# Web dev
cd web && npm run dev         # localhost:4321

# Worker dev (against real KV + secrets)
npx wrangler dev

# QC
bpsai-pair qc list
/run-qc --env prod

# Status
bpsai-pair status
```
