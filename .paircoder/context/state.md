# Current State

> Last updated: 2026-05-09

## What Was Just Done

- 2026-05-09 — PR #25 review-finding follow-up (branch
  `fix/atlas-csp-and-error-boundary`, push-only, NOT merged). All
  three reviewers (nayru, laverna, vaivora) concurred on the
  `connect-src` gap; addressed alongside lower-severity findings:
  (1) added `https://cloudflareinsights.com` to `connect-src` in
  `worker/index.js::CSP_VALUE` so the CF beacon's RUM POST stops
  hitting a second CSP violation on a different directive, paired
  with a third regression-lock test in
  `worker/tests/security_headers.test.js` (64 worker tests passing,
  was 63); (2) extracted `getCspDirective(csp, name)` test helper to
  remove duplicated parse pipeline across the three CSP tests
  (nayru P2 #3); (3) chained `await scatterplot.draw(rows)` inside
  the existing `.then` in `AtlasIsland.tsx` so async draw
  rejections route into the outer `.catch` → `setMountError` and
  the empty-box symptom can't reappear via that path (nayru P1 #2);
  (4) bumped the mount-error overlay from `bg-deep/90` to fully
  opaque `bg-deep` so a half-rendered canvas can't bleed through
  (nayru P2 #5); (5) added an `'unsafe-eval' CSP relaxation +
  Cloudflare beacon allowlist` entry under SECURITY.md "Documented
  exceptions" mirroring the CVE-2026-1839 structure (Accepted
  date / Status / Why-acceptable / Removal trigger), including the
  laverna LOW finding that no SRI is pinned on the CF beacon
  (vaivora P1 + laverna LOW); (6) reframed the architecture.md CSP
  section as the technical *what* and cross-linked SECURITY.md for
  the policy *why*. Web build clean, arch check clean on all
  touched files. One conventional-commits follow-up commit pushed
  to the PR branch.

- 2026-05-09 — Atlas CSP + error-boundary fix (PR
  [#25](https://github.com/BPSAI/pursue-index/pull/25), branch
  `fix/atlas-csp-and-error-boundary`). `/atlas` was rendering chrome but
  the canvas stayed empty because the site CSP blocked
  regl-scatterplot's WebGL shader compilation (regl uses `Function()`
  to evaluate generated GLSL→JS). Added `'unsafe-eval'` to site-wide
  `script-src` (rationale documented in `worker/index.js::CSP_VALUE`
  comment + `docs/architecture.md`); also allowlisted
  `https://static.cloudflareinsights.com` for the CF Web Analytics
  beacon. Wrapped the dynamic `import("regl-scatterplot")` chain in
  `AtlasIsland.tsx` with a `.catch()` that surfaces
  `[ATLAS UNAVAILABLE]` inside the canvas frame on mount failure.
  Regression-locked the directive content with two new tests in
  `worker/tests/security_headers.test.js` (63 worker tests passing).
  Web build clean. PR opened against `main`, NOT merged — operator to
  manually smoke `wrangler dev` against `/atlas` before approving.

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
- Curated `/finds` reading guides (11 entries).
- Novelty detection scaffold with a synthetic placeholder reference corpus (10 passages); Black Vault integration on the backlog.

## Build and Deploy

- **Primary:** Cloudflare Workers Builds, configured via the dashboard. Triggers on push to `main`. Build: `cd web && npm install && npm run build`. Deploy: `npx wrangler deploy`.
- **Manual fallback:** `.github/workflows/deploy-cf.yml` runs the same chain via GitHub Actions on `workflow_dispatch`. Available as a button if Workers Builds stalls.
- **Local:** `npx wrangler deploy` from a clean checkout. Requires `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in env (or `wrangler login`).

## What's Next

### Backlog (priority order)

1. **Curated finds expansion.** Current 11 entries set the editorial bar; corpus has more strong candidates. Plan: `.paircoder/plans/curated-finds.md`.
2. **LLM-cleaned reading text overlay.** Optional reader-mode layer: prose-cleaned OCR text alongside raw transcript, attributed and reversible. Pilot 30 cards before full corpus run. Plan: `.paircoder/plans/llm-cleaned-reading-text.md`.
3. **Black Vault reference corpus.** Replace the placeholder novelty corpus with a real prior-disclosure FOIA archive. Requires upstream permission and threshold recalibration. Plan: `.paircoder/plans/black-vault-reference.md`.
4. **Review-and-correct pipeline.** Accept community OCR transcript corrections via GitHub issues; flow them back into the index. Plan: `.paircoder/plans/review-correct.md`.

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
