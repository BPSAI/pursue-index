# Current State

> Last updated: 2026-05-11 (evening)

## What Was Just Done

**2026-05-11 (evening) — Regression bug hunt + tranche f07601eb ingest + integrity ask landed.**

- **PDF iframe sandbox regression fixed (#48 — direct to main, `4e03a1d`).** Chrome 147 PDFium changed behavior: any `<iframe sandbox=...>` now suppresses inline PDF rendering regardless of allow-* tokens. Every card detail page on desktop Chrome was shipping a blank iframe; mobile masked it (system PDF viewers). Trust basis for dropping sandbox: post-PR #27 the iframe loads only same-origin `/pdf/<card_id>.pdf` from our R2 mirror, not adversarial content. CSP `frame-ancestors 'self'` + `X-Frame-Options: SAMEORIGIN` + worker card_id regex validation provide defense-in-depth.
- **Security bundle (`b6dba3f`).** HSTS header `max-age=31536000; includeSubDomains` (preload deliberately omitted) + RFC 9116 `/.well-known/security.txt` per operator audit. Clears 3 of the 11 audit items; DMARC + Always-Use-HTTPS + AI-bot toggles are operator dashboard/DNS actions.
- **Reader/Cleaned pagination regression fixed in two passes (`6d41ac6` then `ed93bb0`).** Operator-reported "first click works, then stuck" across both Reader and Cleaned modes, desktop + mobile. Reproduced live: rapid clicks within a single tick batched correctly (state 1→5), but sequential clicks with any wait failed after the first. The first-pass useReducer fix did not clear it on prod. Second pass refactored to ref-driven `navigateTo(target)`: handlers read `activePageRef.current` + `totalRef.current` live, compute the explicit target page, dispatch a `set` action, and do `history.replaceState` + iframe sync inline in the same call. Eliminates the deferred-useEffect race that was the root cause.
- **Mobile title overflow fixed (`e0d7add`).** `break-words` on the card title h1 so long technical filenames wrap on narrow viewports.
- **Augment loader hardened (`d60d9d9`).** Four corrupt rows (lines 448–451) in `alex-zhang42-corpus.jsonl` were aborting the entire embed. Parser now skips per-row with a logged sample and a 5% wholesale-corruption guardrail.
- **Cleaned-mode fetch race fixed (`e5defd7`).** The pre-existing "sometimes loads, sometimes doesn't — refresh fixes it" hang: useEffect dep `cleanedStatus` caused the fetch effect to re-fire on every status transition (idle → loading → loaded), racing with the 7.7 MB `r.json()` parse and stranding state on "loading." Gated via `useRef` flag; deps shrink to `[mode, base]`; cleanup-cancellation on unmount/mode-switch.
- **Tranche f07601eb ingested.** Scrape → 158 cards (was 119; +39: 28 VIDs + 14 IMGs + 0 net new PDFs). Download → 129/158 (the 29 missing are DVID-hosted videos; `PURSUE_DOWNLOAD_VIDEOS` default off). OCR → 116 PDF cards (no new pages). Embed → 1216 new embeddings, 2911 skipped, 418,704 tokens, **~$0.025**. Then re-run with augment-from: 1132 pages got VLM image tags (lenient parser caught the 4 corrupt rows).
- **API key rotation.** Operator rotated `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY` after the assistant accidentally printed both via a misused `${VAR:-default}` bash expansion. New keys deployed to `.env` (local) and CF Worker secrets (live via `npx wrangler secret put`). No GitHub Actions reference either key.

**2026-05-11 — Fact-check pass + LLM-cleaned pilot resume.**

- A r/UFOs reader DM'd the operator pointing out that the Muroc-1947 entry stated Roswell was "2,000 miles east" of Muroc/Edwards AFB. Actual great-circle distance is ~800 mi. Fixed directly on `main` as `5c8a0a9`.
- Defensive fact-check pass across all 14 `/finds` entries (via Explore agent). Verified Apollo 17, Kenneth Arnold, LaPaz fireballs, Mantell, Rhodes Phoenix, FBI 62-HQ-83894 sectioning, LaPaz/Institute of Meteoritics. **No additional factual errors.**
- One HIGH-severity ambiguity surfaced and fixed: D23 entry's manifest `incident_date: 10/31/2023` vs MISREP Zulu DTGs (Oct 24, 2023). In-entry clarifier landed as `d7258e9`. Manifest-field correction continues as Issue #36.
- LLM-cleaned pilot resume kicked off: `pursue clean run --cards <30> --budget-usd 0.75`. PR #46's content-filter graceful-skip validated in production (page 93 of card `7d58f0cac741650a`). Pilot hit the cap at 3 cards; extension pilot on 3 modern MISREPs (D23/D32/D33) added at $0.08, zero skips. Combined pilot output: 385 cleaned pages + 88 skip rows across 6 cards for $0.83.
- Spot-check checklist for the pilot output landed at `.paircoder/plans/llm-cleaned-pilot-spotcheck.md` — 40 checks across 5 pages, ship-readiness criteria explicit. Manual spot-check executed; **0 hard signals + 1 soft signal across 5 pages → GO verdict**. Lone soft signal: D33 p1 `1.48 → 1.4a` interpretive cleanup (single-character OCR fix in context, defensible but worth documenting in methodology).
- Full corpus pass launched: `pursue clean run --budget-usd 25.00`. Running in background; projected $8–12 spend across ~4,153 pages.
- QC engine plan landed: `.paircoder/plans/clean-quality-review.md` — LLM-judge layer over the cleanup output, ~$6 (Haiku judge) or ~$42 (Sonnet judge) per corpus pass, with explicit calibration discipline (20-page operator sample per run).

**2026-05-10 — v1.0.0 shipping run (19 PRs merged).**

- v1.0.0 tag + GitHub release shipped against PURSUE Release 01.
- 14 finds entries live (was 11): added D32 (#32), D23 (#34), D33 (#35).
- LLM-cleaned reading text overlay shipped as **dark code** (#37): pipeline + CLI + UI toggle live, `pages-cleaned.json` not yet produced. Toggle reads "Cleaned text not yet available for this card." Full corpus run is the gate to flip live (pilot in progress, see above).
- Content-filter graceful-skip (#46): runner no longer crashes on Anthropic moderation rejections; writes a `content_filter` skip row and continues.
- Self-hosted PDFs via Cloudflare R2 (#27) — fixes war.gov framing-block iframe issue.
- Atlas regl-scatterplot fixes (#25, #26, #30, #31): CSP unsafe-eval, UMAP [-1,1] normalization, colorBy/opacityBy lookup-array config, mobile cluster fallback retired.
- Search title-match highlight + dropped fuzzy expansion (#29).
- alex-zhang42 augmented retrieval elevated to project differentiator (#41); `/methodology` deep-links to OCR benchmark (#42).
- Repo audit cleanup: redactions + housekeeping (#44), accessibility audit + remediation plan (#45), pursue-vision-augment Phase 2 plan (#43), CI tightening (#22, #23, #24, #28), agent-memory untracked from public repo (#21 era).

## Known dark code

| Feature | Implementation | Wiring | Validation | Output | Live? |
|---|---|---|---|---|---|

No dark code currently. The LLM-cleaned reading text shipped fully on 2026-05-11 (PR #37 + #46 + `0035f3f` for the asset + post-deploy pagination/race fixes). The dark-code row from earlier in the day cleared with `0035f3f`; subsequent fixes were live-bug regression patches, not unwired features.

## Current Focus

Public site live at <https://pursueindex.com>. Full pipeline (scrape →
download → OCR → embed → serve) shipped end-to-end against PURSUE
Release 01. Chat interface live with mandatory `[card_id:page]`
citation discipline and abstention behavior. Repository is public
(`BPSAI/pursue-index`, Apache-2.0).

A complementary CC0 dataset (`alex-zhang42/ufo-pursue-open-atlas`)
released for the same source with VLM-described image content; we
credit it on `/methodology` under Related Work and ingest its
image-description blocks into our retrieval index.

## Active Plan

| Stage     | Status   | Output                                                             |
|-----------|----------|--------------------------------------------------------------------|
| scrape    | shipped  | curl_cffi + Chrome TLS, 161-card manifest, hash-pinned             |
| download  | shipped  | 116 PDFs + 14 images on NAS via content-addressable layout         |
| ocr       | shipped  | 3,529 Surya pages + 624 LLM-cleaned pages (auto-mode), 4,153 total |
| embed     | shipped  | Voyage-3 1024d float16, ~8 MB in-browser payload (1,208 augmented) |
| serve     | shipped  | Astro static + CF Worker (CORS-locked, 5/IP/24h, $100/day cap)     |
| chat      | shipped  | RAG with mandatory citations, anonymous + BYOK tiers               |
| novelty   | shipped  | machinery + UI; placeholder reference corpus (10 passages)         |
| atlas     | shipped  | 2D UMAP semantic browser at `/atlas` (4,119 dots, regl-scatterplot) |

## What's Live

- Custom domain at `pursueindex.com` on Cloudflare Workers + Static Assets.
- Full-text + semantic search across 4,153 OCR'd pages (MiniSearch lexical + Voyage-3 embeddings, both browser-side).
- OCR pipeline: Surya (GPU, transformer-based) primary + Anthropic vision LLM fallback for low-confidence pages.
- RAG chat with mandatory citations: anonymous tier (server-funded, 5/IP/24h, $100/day budget cap) and BYOK tier (browser-direct to Anthropic).
- Faceted search filters on `/search` (agency, incident date, redacted-only).
- Per-entry OG image cards for `/finds/<slug>` social sharing.
- Reader-mode toggle on card detail pages with `j`/`k` page navigation; iframed PDF stays in sync via `#page=N` deep linking.
- `/atlas` semantic browser: clickable UMAP projection of all 4,119 page embeddings, MiniSearch-backed search highlight, mobile cluster-list fallback.
- Public API documentation at `/api`.
- Auto-poll for new tranches: GitHub Actions cron every 6 hours fetches the upstream CSV, hashes it, opens an issue on change or fetch failure.
- Tranche diff page surfaces per-card deltas when the upstream CSV changes.
- Curated `/finds` reading guides (14 entries; added D32, D23, D33 in the 2026-05-10 run).
- Novelty detection scaffold with a synthetic placeholder reference corpus (10 passages); Black Vault integration on the backlog.
- PDF hosting self-managed from Cloudflare R2 (was war.gov direct iframe; broken by upstream framing-block mid-build).
- alex-zhang42 CC0 augmented-retrieval dataset surfaced as project differentiator on `/methodology` and in `/api/retrieve` responses (1,208 augmented chunks in the embedding index).

## Build and Deploy

- **Primary:** Cloudflare Workers Builds, configured via the dashboard. Triggers on push to `main`. Build: `cd web && npm install && npm run build`. Deploy: `npx wrangler deploy`.
- **Manual fallback:** `.github/workflows/deploy-cf.yml` runs the same chain via GitHub Actions on `workflow_dispatch`. Available as a button if Workers Builds stalls.
- **Local:** `npx wrangler deploy` from a clean checkout. Requires `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in env (or `wrangler login`).

## What's Next

### Active (next priority, in operator-stated order)

1. **Archive integrity — snapshot rotation + removal detection.** Operator-explicit priority before gallery: "make sure that whatever may have come with this latest drop is not overwriting something that we had before. People have complained about the epstein files getting pages removed etc. quietly and are already bringing it up in relation to this project." Current state: `DiffIsland` is already wired to read `/data/snapshots/index.json` + per-snapshot manifests, but the snapshots directory doesn't exist and the scrape stage doesn't write prior manifests anywhere except git history. CSV is archived per-fetch (`csv_archive_dir`); manifests are not. Required: (a) snapshot rotation in `scrape_run_cmd` — copy old `latest.json` to `data/manifests/snapshots/<csv_sha>.json` before overwriting; (b) backfill the last-known prior manifest from git so the diff page has *something* to compare against today; (c) removal detection that opens a `card-removed-upstream` issue with the specifics when cards disappear between scrapes; (d) preservation guarantee for R2 mirrored PDFs on removed cards (already true since download stage doesn't delete, but document and surface in UI). **Surface evidence**: the 2026-05-11 augment-corpus join shipped a 7% miss rate against the new manifest, ~289 augment rows pointing at URLs our manifest no longer has — strong signal that upstream removed/renamed cards in this tranche or the prior one. Worth diffing carefully.

2. **VID downloads + ingest the 28 video cards in current manifest.** `PURSUE_DOWNLOAD_VIDEOS` is default off; downloader skips VIDs. Operator noted upstream site offers bulk download links for videos. Path: either flip the flag and ingest via `dvids_video_id` (per-card from DVIDS), or fetch the bulk archive from war.gov. After download, decide on R2 mirror vs. external-link-only (videos are GB-scale).

3. **Gallery surface build + deploy** (operator gate: after archive integrity). The current 2026-05-11 tranche is 28 VIDs + 14 IMGs + 0 new PDFs, which highlights the discoverability gap for non-text cards. Plan: `.paircoder/plans/visual-browse-surface.md`. Move up from backlog.

4. **Tranche `0d7e9ba1` not yet scraped.** Auto-poll workflow caught a second CSV change at 2026-05-11T18:40Z → tranche-detected issue + commit `dc16062` updating `data/last-known-csv-sha.txt`. Our current `latest.json` is the prior tranche `f07601eb`. Run `pursue scrape` again when ready (best done AFTER snapshot rotation is in place so we don't lose tranche-f07601eb's manifest).

5. **QC engine plan landed (lower-priority thread).** `.paircoder/plans/clean-quality-review.md` — LLM-judge layer over cleanup output. Idempotent sidecar `pages_cleaned_qc.jsonl` with 8 structured checks per page. Calibration discipline: 20-page operator sample per corpus run. Pilots when capacity opens up.

6. **`web/src/content/finds/hanawalt-cobalt-ray-1966.mdx` awaiting review.** Untracked operator draft from last session, opened in IDE today. 64-line curated entry on FBI 62-HQ-83894 Section 10 pages 53–56 (Hanawalt cobalt-ray telegram). Sharp methodology framing on the difference between "document the FBI filed" and "claim the FBI endorsed." Ready to commit on operator green-light.

### Backlog (priority order)

1. **Black Vault reference corpus.** Replace the placeholder novelty corpus with a real prior-disclosure FOIA archive. Engagement done; technical phases discovery → fetch → OCR → embed → calibrate are unblocked. Plan: `.paircoder/plans/black-vault-reference.md`.
2. **Accessibility audit + remediation.** Plan landed 2026-05-10 (#45) covering WCAG 2.2 AA targets including the regl-scatterplot atlas a11y challenges. Plan: `.paircoder/plans/accessibility-audit-and-remediation.md`.
3. **`/gallery` visual-browse-surface.** Image-content browse page alongside the textual /search and the spatial /atlas. Plan: `.paircoder/plans/visual-browse-surface.md`.
4. **pursue-vision-augment Phase 2.** Our own VLM pass alongside the alex-zhang42 augmented retrieval, with per-page provenance distinguishing the two sources. Plan: `.paircoder/plans/pursue-vision-augment.md`.
5. **Curated finds expansion.** 14 entries set the editorial bar; corpus has more strong candidates. Plan: `.paircoder/plans/curated-finds.md`.
6. **Review-and-correct pipeline.** Accept community OCR transcript corrections via GitHub issues; flow them back into the index. Plan: `.paircoder/plans/review-correct.md`.
7. **Autonomous finds pipeline.** Background drafting of finds entries from new tranches, operator-gated for editorial publish. Plan: `.paircoder/plans/autonomous-finds-pipeline.md`.

### Open issues

- **#36** — Manifest `incident_date` audit across modern D## entries. In-entry clarifier for D23 landed 2026-05-11 (`d7258e9`); manifest-field correction still pending. Priority: Low.

## Reproducibility

The corpus pipeline is fully scripted and idempotent. From a clean
clone with the upstream CSV available:

```bash
pursue scrape run                                        # writes manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json
```

Each stage is content-addressed by `card_id = sha256(asset_url || title)[:16]`,
so partial reruns converge on the same final state regardless of order.
The manifest carries `csv_sha256` so upstream changes are detectable
in O(bytes-of-CSV).

## Quick Commands

```bash
# Pipeline (idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json --augment-from data/external/alex-zhang42-corpus.jsonl

# Tests
pytest -x                      # python
npm --prefix worker test       # worker
cd web && npm run build        # web (~169 pages)

# Web dev
cd web && npm run dev          # localhost:4321

# Worker dev (against real KV + secrets)
npx wrangler dev
```

## Blockers

None.
