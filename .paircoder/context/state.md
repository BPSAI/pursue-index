# Current State

> Last updated: 2026-05-11

## What Was Just Done

**2026-05-11 — Fact-check pass + LLM-cleaned pilot resume.**

- A r/UFOs reader DM'd the operator pointing out that the Muroc-1947 entry stated Roswell was "2,000 miles east" of Muroc/Edwards AFB. Actual great-circle distance is ~800 mi. Fixed directly on `main` as `5c8a0a9`.
- Defensive fact-check pass across all 14 `/finds` entries (via Explore agent). Verified Apollo 17, Kenneth Arnold, LaPaz fireballs, Mantell, Rhodes Phoenix, FBI 62-HQ-83894 sectioning, LaPaz/Institute of Meteoritics. **No additional factual errors.**
- One HIGH-severity ambiguity surfaced and fixed: D23 entry's manifest `incident_date: 10/31/2023` vs MISREP Zulu DTGs (Oct 24, 2023). In-entry clarifier landed as `d7258e9`. Manifest-field correction continues as Issue #36.
- LLM-cleaned pilot resume kicked off: `pursue clean run --cards <30> --budget-usd 0.75`. PR #46's content-filter graceful-skip validated in production (page 93 of card `7d58f0cac741650a`).
- Spot-check checklist for the pilot output landed at `.paircoder/plans/llm-cleaned-pilot-spotcheck.md` — 40 checks across 5 pages, ship-readiness criteria explicit.

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
| LLM-cleaned reading text | ✓ (#37, #46) | ✓ (toggle on `/card/:id`) | partial (pilot in progress) | not yet (`pages-cleaned.json` missing) | **No — toggle reads "not available"** |

This row clears when the pilot lands cleanly, spot-check passes, full-corpus run completes, and `scripts/build_pages_cleaned.py` produces the deployable asset. See `.paircoder/plans/llm-cleaned-pilot-spotcheck.md` for the QA bar.

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

### Active (in-flight today)

1. **LLM-cleaned reading text — pilot resume.** Pilot is *running now* (`/tmp/pursue-pilot/run.log`; monitor armed). Next: spot-check 5 sidecar pages per `llm-cleaned-pilot-spotcheck.md`, then full-corpus run with `--budget-usd 25.00`, then `python scripts/build_pages_cleaned.py` to flip the toggle live. Open strategic question for after pilot: content-filter fallback strategy (option 1/2/3 in `project_pickup_2026_05_11.md` memory). Plan: `.paircoder/plans/llm-cleaned-reading-text.md`.

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
