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
| DVIDS Video ID      | Present on video/audio entries; citable DVIDS provenance id (playback served from our R2 archive) |
| Video Title         |                                                                |
| Agency              | DOW / FBI / NASA / DOS                                         |
| Incident Date       | "N/A" treated as null                                          |
| Incident Location   | "N/A" treated as null                                          |
| PDF \| Image Link   | Direct asset URL                                               |
| Modal Image         | Thumbnail shown in the card and modal                          |

## Stages

| # | Stage    | Inputs                | Outputs                              | Status |
|---|----------|-----------------------|--------------------------------------|--------|
| 1 | scrape   | DOW CSV               | `manifest.json`                      | ✅ shipped |
| 2 | download | manifest              | PDFs/IMGs in `data/{pdfs,images}/`   | ✅ shipped |
| 3 | ocr      | PDFs                  | `pages.jsonl` per card               | ✅ shipped |
| 4 | embed    | manifest + OCR output | Voyage-3 float16 browser payload     | ✅ shipped |
| 5 | serve    | embed payload + worker | Static site + Cloudflare Worker chat | ✅ shipped |

The 30-minute CSV poll drives a parallel **archive** lane: per-fetch CSV bytes are committed content-addressed, prior manifests rotate into `data/manifests/snapshots/<csv_sha>.json`, and every referenced PDF/IMG asset is mirrored into R2 keyed by `byte_sha256`. A daily verify cron catches silent upstream overlays.

## Idempotency contract

Every stage is idempotent against a content-hashed manifest. The manifest carries `csv_sha256` (hash of raw bytes) so we can detect upstream changes cheaply. Re-running on an unchanged manifest is a no-op modulo timestamps.

## The card_id

`card_id = sha256(asset_url || title)[:16]`. The URL is the primary stable identifier; title is the fallback for any hypothetical metadata-only entries. Short enough to use as a directory name on the NAS.

## Multi-modal handling

Not every PURSUE entry is a PDF. Of the 158 in PURSUE Release 01 (as of tranche 65572b38, 2026-05-12): 116 PDFs, 28 videos, 14 images.

- **PDFs**: download → OCR → index. Standard flow.
- **Images**: download → store. Future: vision analysis (the DOW shipped these as raw infrared stills; OCR isn't useful but visual feature extraction may be).
- **Videos & audio**: fetched via the DVIDS API to resolve a download URL, then archived into our Cloudflare R2 (content-addressed `archive/<sha>.mp4` + a `<card_id>.mp4` current-pointer) and served from there — DVIDS remains only the citable provenance source (the public video page), not the playback path. Download is off by default (`PURSUE_DOWNLOAD_VIDEOS=false`). Audio is transcribed via AssemblyAI/Aurora.

## OCR strategy

Historical FBI scans vary wildly in quality. The operated engine is
`llm-dots`: **Claude Sonnet 4.6** vision reads every page, with local
**dots.mocr** as a per-page content-filter (HTTP 400) backstop. The
engine seam in `ocr/pipeline.py` (`rasterize_pdf`, `ocr_image`,
`_run_engine`) is engine-agnostic so additional engines can land
without disturbing orchestration.

- **Claude Sonnet 4.6 vision** (operated primary, `--engine llm`) —
  reads each page image directly. Chosen via the published bake-off
  (`docs/ocr-benchmark.md`) for its accuracy on degraded scans. Plain
  `--engine llm` 400s on the rare page Anthropic's output filter blocks,
  which is why the operated engine is `llm-dots`, not `llm`.
- **dots.mocr** (`--engine dots`, and the backstop half of `llm-dots`) —
  local model run in an **isolated venv** (`PURSUE_DOTS_PYTHON`). Re-OCRs
  exactly the pages Sonnet's filter 400s, so a mixed doc keeps Sonnet
  everywhere except the filter-blocked page.
- **AssemblyAI** — transcribes AUD (audio) cards.
- **Retired** (do not operate): Surya, Tesseract, and the old `auto`
  resolver / Haiku 4.5 fallback.

Under `llm-dots`, Sonnet reads every page and dots.mocr backstops only the
filter-blocked ones. Engine + confidence are recorded per page in
`pages.jsonl`.

## Search

Search is browser-side: MiniSearch (lexical) over the OCR text plus
Voyage-3 embeddings for semantic / `/api/retrieve`. No server query
path. The SQLAlchemy schema in `src/pursue_index/index/` is an optional
forensic-ingest target — not in the deployed read path.

## What lives where

- **Repo**: code, `pyproject.toml`, manifests (small JSON, version-controlled), migrations, docs, content-addressed CSV bytes (`data/raw/csv/<sha>.csv`) and rotated manifest snapshots (`data/manifests/snapshots/`).
- **NAS** (`PURSUE_DATA_ROOT`): `pdfs/`, `images/`, `videos/`, `ocr/`, `logs/`.
- **R2**: `archive/<byte_sha256>.<ext>` mirror of every referenced PDF/IMG asset (silent-overlay-resistant byte-history archive).
- **Postgres** (optional forensic-ingest target; not used by the deployed site): `cards`, `pages`.

The split is enforced by config: `PURSUE_DATA_ROOT` and `PURSUE_MANIFESTS_DIR` are independent, so manifests stay in the repo regardless of where bulk data is parked.

## Re-running on a new tranche

The CSV URL is stable; DOW updates the file in place when new tranches drop.

```bash
pursue scrape run                          # writes data/manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine llm-dots
pursue embed run --manifest data/manifests/latest.json
```

Each stage skips work it's already done for unchanged `card_id`s. The CSV archive (`data/raw/csv/<sha>.csv`, content-addressed and committed) gives us a forensic trail of how the source has evolved over time, independent of the manifests we generate.

A 30-minute cron (`.github/workflows/poll-pursue.yml`) watches the upstream CSV via the curl_cffi Chrome-impersonate path; on every fetch it preserves the raw CSV bytes content-addressed under `data/raw/csv/<sha>.csv` and on sha change opens a `tranche-detected` issue. The same workflow runs a sentinel PDF-fetch health check (`scripts/pdf_health_check.py`, deterministic lex-smallest PDF card from the manifest) over the same TLS path so PDF-only Akamai gating shifts surface within 30 minutes instead of waiting for an operator-attended download stage to fail. A companion `verify-assets-daily.yml` workflow runs at 06:07 UTC daily and HEAD-checks every referenced asset against its registered byte_sha — same-URL-different-bytes overlays land as a new `archive/<byte_sha>.<ext>` row and open a `silent-overlay-detected` issue.

## Web build chain (post-embed)

The static site shipped to Cloudflare reads three browser-side payloads
that derive from the embed/index outputs. They have an implicit
ordering: a fresh `pursue embed run` invalidates all three, and the web
build must rebuild them all before re-deploying or the rendered pages
will reference deduped rows that don't exist in the deployed payload.

| # | Script                              | Reads                                                | Writes                                            |
|---|-------------------------------------|------------------------------------------------------|---------------------------------------------------|
| 1 | `pursue embed run`                  | OCR pages + manifest                                 | `{embeddings_root}/{model}/{vectors.bin,index.json}` |
| 2 | `scripts/build_search_data.py`      | OCR pages                                            | `web/public/data/pages.json`                      |
| 3 | `scripts/build_embed_data.py`       | embed root                                           | `web/public/data/{embeddings.bin,embed_index.json}` (float16) |
| 4 | `scripts/build_atlas_layout.py`     | embed root (float32) **or** deployed payload (float16) | `web/public/data/atlas-layout.json`               |
| 5 | `cd web && npm run build`           | all of the above                                     | `web/dist/` (Cloudflare Workers static assets)    |

`build_atlas_layout.py` prefers the native float32 `vectors.bin` because
UMAP is sensitive to the float16 → float32 round-trip (the deployed
fallback gets you a *near* layout, not an identical one). When the NAS
isn't mounted (CI / clean clones), pass `--from-published web/public/data/`
to read the deployed float16 payload — accept the small precision delta
versus refusing to build.

**Order matters.** A fresh `pursue embed run` invalidates 2–4;
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

### Deploy paths

There are three ways the live Worker can be updated, in order of
preference:

1. **Primary — CF Workers Builds.** Configured via the Cloudflare
   dashboard (`build: cd web && npm install && npm run build`,
   `deploy: npx wrangler deploy`). Triggers on push to `main`. This
   is the path documented in `wrangler.jsonc` and is what runs on a
   healthy day.
2. **Fallback — `.github/workflows/deploy-cf.yml`.** Same deploy from
   GH Actions, **manual-only** (`workflow_dispatch`). Exists because
   CF Workers Builds has stalled multiple times (notably the
   2026-05-09 cluster — PRs #6 through #17 merged but the live Worker
   stayed pinned to a pre-#6 build until the operator manually
   deployed). Originally triggered on push to `main` for paths that
   affect the bundle (`web/**`, `worker/**`, `wrangler.jsonc`,
   `data/manifests/**`); flipped to manual-only on 2026-05-09 once
   CF Workers Builds was confirmed reliably triggering on push, since
   running both paths on every push doubled the Version IDs in the
   Cloudflare Versions list and doubled the `deploy-failure` issue
   noise for no functional gain (vaivora flagged the dual-pipeline
   concurrency caveat in PR #18 review). Run it from the Actions UI
   ("Run workflow") whenever the dashboard pipeline stalls. On
   failure it opens or updates a `deploy-failure` issue keyed off the
   run URL; with auto-firing disabled, an open issue persists until
   the operator either re-runs a successful manual deploy and closes
   it or closes it directly. The workflow's `concurrency: deploy-cf`
   group still serializes manual runs against each other, so a quick
   double-click on "Run workflow" cancels the older queued run rather
   than racing two `wrangler deploy` calls.
3. **Manual — `npx wrangler deploy` from a local repo.** Last-resort
   path the operator uses when both above are stuck. Requires
   `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` in env (or `wrangler login`).

Token-rot detection runs out-of-band via
`.github/workflows/cf-token-health.yml` — a weekly Monday-12:00-UTC
`workflow_dispatch`-able cron that calls `npx wrangler whoami` against
the same `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets the
fallback deploy uses. With the deploy workflow flipped to manual-only
(see path #2), those secrets are no longer exercised on every push, so
a rotated-but-not-updated token would otherwise sit broken until the
next manual deploy attempt. The health check opens or updates a
`cf-token-health-failure` issue on probe failure, mirroring the
`deploy-failure` issue pattern. Recommended by laverna in the PR #24
security review.

### /api/* dispatch contract

Integration-boundary smoke test runs on every PR via
`.github/workflows/smoke-api-dispatch.yml` and asserts the dispatch
contract end-to-end against `wrangler dev` + a freshly-built `web/dist`.
The unit tests in `worker/tests/api_gate.test.js` stub the ASSETS
binding; the smoke script does not. New routes added to either
`WORKER_API_PATHS` or `web/src/pages/api*.astro` should also be added to
`scripts/smoke_api_dispatch.sh` so the contract test stays
comprehensive.

### Self-hosted PDFs (R2 mirror)

`worker/pdf.js` handles `GET /pdf/<card_id>.pdf` against the R2 binding
`PDFS` (bucket `pursue-pdfs`, key format `<card_id>.pdf`). The handler
validates `card_id` against `/^[a-f0-9]{16}$/`, range-aware
streams the body back with `Content-Type: application/pdf` and
`Cache-Control: public, max-age=31536000, immutable` (URLs are
content-addressed; the bytes can't change without changing the
card_id), and 404s on missing objects.

We mirror the corpus rather than embed war.gov directly because in
May 2026 war.gov / Akamai shipped cross-origin framing protection
(`X-Frame-Options` / `frame-ancestors`) that started returning
`chrome-error://chromewebdata/` for iframe embeds while leaving direct
opens working. The card-detail page's iframe `src` is now
`/pdf/${card.card_id}.pdf`, but the OPEN ↗ button on that same page
still points at `card.asset_url` on `www.war.gov` — war.gov stays the
cite-of-record. The R2 mirror is just a hosting layer. Adding new PDFs
requires the operator to create or update the R2 object via the CF
dashboard or `wrangler r2 object put`; the binding name `PDFS` is
load-bearing and referenced from `worker/pdf.js::serveR2Pdf`.

### Content-Security-Policy notes

`script-src` includes `'unsafe-eval'`. WebGL shader compilation in
`regl-scatterplot` (atlas page) requires runtime `Function()`
evaluation — without it the entire `/atlas` visualization fails to
initialize. Site-wide rather than `/atlas`-scoped so the Worker
doesn't need a per-route CSP function coupled to asset paths.
`script-src` also allowlists `https://static.cloudflareinsights.com`
for the first-party CF Web Analytics beacon, and `connect-src`
allowlists `https://cloudflareinsights.com` for the beacon's RUM
telemetry POST (different subdomain than the script host — both are
needed). Regression-locked by `worker/tests/security_headers.test.js`
so a future tightening can't silently break /atlas or analytics.

The **policy rationale** for accepting `'unsafe-eval'` (no
user-input → eval path, same-origin scripts, blast-radius bounded by
`connect-src`, negligible delta over the existing `'unsafe-inline'`
posture, and the SRI-pin gap on the CF beacon) lives in
`SECURITY.md` under "Documented exceptions" — the same pattern used
for the CVE-2026-1839 / `transformers` exception. This section is
the technical *where it lives*; SECURITY.md is the policy *why*.

`frame-src` is `'self'` only. It used to allow `https://www.war.gov`
for the cross-origin PDF iframe on `/card/<id>`, but PDFs are now
served same-origin from the R2 mirror (see "Self-hosted PDFs (R2
mirror)" above), so the cross-origin permission is no longer needed.
`img-src` still allows `https://www.war.gov` because non-PDF cards
keep `card.modal_image_url` on war.gov for thumbnails.
