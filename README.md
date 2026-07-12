# pursue-index

> A citable, full-text-searchable interface to the U.S. Department of War's
> **Presidential Unsealing and Reporting System for UAP Encounters (PURSUE)**
> document releases.

Live: **<https://pursueindex.com>**
Source: **<https://www.war.gov/UFO/>**
Code: **<https://github.com/BPSAI/pursue-index>**

---

## What this is

The DOW publishes the PURSUE corpus as a single CSV (currently `uap-data.csv`,
rotated twice from earlier filenames as new releases landed) rendered inside
a DataTables widget. That's fine for browsing one record at a time. It's
useless for searching the actual contents of the documents.

`pursue-index` is the first end-to-end pipeline and reader for that corpus:

1. Snapshot the upstream CSV and pin its SHA-256 in a hash-stable manifest.
2. Fetch every referenced PDF / image idempotently into content-addressable storage.
3. OCR every PDF page with the `llm-dots` engine — Claude Sonnet 4.6 vision as
   the operated primary (chosen via a published bake-off), with local dots.mocr
   as the content-filter (HTTP 400) backstop for the rare page Sonnet's output
   filter blocks — recording per-page engine + confidence in `pages.jsonl`.
   AUD (audio) cards are transcribed by AssemblyAI.
4. Build an in-browser search index over the OCR transcripts.
5. Serve the result as a static site with mandatory citations on every claim.

Every record traces back to a specific page of a specific war.gov PDF.
Methodology is published. Numbers are reproducible from a clean clone.

## What's live

- **Custom domain.** [pursueindex.com](https://pursueindex.com) on Cloudflare
  Workers + Static Assets.
- **Full-text + semantic search** across **~7,800 OCR'd pages** spanning
  **175 PDF cards** (294 total cards incl. video/audio/image) from PURSUE
  Releases 01–03. MiniSearch lexical index +
  Voyage-3 embeddings, both browser-side; no server. The `/search` route
  adds a faceted filter rail (agency multi-select, incident-date range,
  redacted-only) over the lexical index; filter state round-trips through
  the URL so links are shareable.
- **OCR pipeline.** The operated engine is `llm-dots`: Claude Sonnet 4.6 vision
  as the per-page primary (chosen via a published bake-off), with local
  dots.mocr as the content-filter (HTTP 400) backstop for the rare page
  Sonnet's output filter blocks. Per-page engine + confidence are recorded in
  `pages.jsonl`. AUD (audio) cards are transcribed by AssemblyAI. (Surya and
  Tesseract are retired.)
- **Archive integrity.** Every CSV byte stream we fetch is committed
  content-addressed; prior manifests are rotated into per-snapshot JSON;
  every referenced PDF/IMG is mirrored into R2 keyed by `byte_sha256`;
  a daily byte-verify cron opens an issue on any silent
  same-URL-different-bytes overlay.
- **/gallery surface.** Image + video tile browse alongside textual
  /search and spatial /atlas. Tiles use poster frames drawn from our
  R2 video archive (the A/V itself streams from R2, content-addressed;
  DVIDS is the citable provenance source, not the playback path) and
  page-1 WebP thumbnails for PDFs. Type filters + year
  buckets; ~3.1 MB total static assets.
- **/removed surface.** Index of cards we preserved here after the
  upstream version was pulled, swapped, or rewritten. Each entry points
  at the prior-manifest snapshot's byte-history archive so the cited
  bytes stay reachable.
- **RAG chat with mandatory citations.** Anonymous tier (server-funded,
  5/IP/24h, $100/day budget cap) and BYOK tier (browser-direct to
  Anthropic). Both share the same UI. Off-corpus questions abstain
  rather than hallucinate; every cited claim is `[card_id:page]` and
  resolves to a primary-source page.
- **Published quality benchmark.** Five-PDF golden set covering the engine
  failure modes (clean typewriter / faded carbon / multi-column / redacted /
  long debriefing). The May-2026 bake-off (re-validated 2026-06) compared every
  credible engine; **Claude Sonnet 4.6 is the operated answer** (best on the
  degraded golden set). See [`docs/ocr-benchmark.md`](docs/ocr-benchmark.md) and
  [/methodology](https://pursueindex.com/methodology).
- **Tranche diff.** Every CSV byte stream we fetch is committed at
  `data/raw/csv/<sha>.csv` and the prior manifest is rotated into
  `data/manifests/snapshots/<csv_sha>.json`; the diff page surfaces
  per-card deltas when the upstream CSV changes.
- **Pages.** [/about](https://pursueindex.com/about),
  [/methodology](https://pursueindex.com/methodology),
  [/cite](https://pursueindex.com/cite),
  [/support](https://pursueindex.com/support), and a small set of
  curated [/finds](https://pursueindex.com/finds) entries — primary-source
  reading guides written against specific pages of specific cards.
- **Novelty detection (machinery + UI).** `pursue novelty compute` runs
  cosine top-1 vs a reference embedding index and tags each card as
  `novel` / `partial` / `previously-disclosed`. The index page has a
  DISCLOSURE filter chip; the card detail page has a Provenance panel
  showing the top-3 reference matches. Currently shipping with a small
  synthetic placeholder reference corpus (10 hand-crafted public-domain
  passages from Roswell 1947, Project Blue Book, the Hottel memo, etc.) —
  full Black Vault integration is on the post-launch backlog.
- **2D semantic browser.** [/atlas](https://pursueindex.com/atlas) projects
  every OCR'd page from the 1024-dim Voyage-3 embedding space into 2D via
  UMAP (`random_state=42`). 4,127 dots, color-coded by agency, pan / zoom
  / lasso via WebGL (`regl-scatterplot`); type to dim non-matches via the
  same MiniSearch index `/search` uses. Sub-400px viewports get a k-means
  cluster-list fallback. The layout is a low-dimensional approximation,
  not ground-truth topic groupings — see
  [/methodology#atlas](https://pursueindex.com/methodology#atlas) for
  projection details and tradeoffs.

## On the post-launch backlog

- **Curated finds expansion.** More hand-authored reading guides; current
  set is intentionally small to set the editorial bar.
- **Black Vault reference corpus.** Acquire + OCR + embed the canonical
  prior-disclosure FOIA archive (~100k–500k pages) so the novelty
  detection moves from "methodology demo" to "real coverage measurement"
  for every card.
- **Auto-poll for new tranches — Layer 2.** Layer 1 (lightweight cron
  poll detecting upstream CSV changes, every 30 minutes) is shipped in
  [`.github/workflows/poll-pursue.yml`](.github/workflows/poll-pursue.yml);
  on change it commits both the new sha and the raw CSV bytes
  (content-addressed) and opens a `tranche-detected` issue. Layer 2
  (heavy ingest pipeline trigger) is operator-attended by design —
  GPU provisioning, cost, and content review keep auto-run off the
  table at v1.
- **Review-and-correct pipeline.** Post-launch, accept community
  corrections on OCR transcripts via GitHub issues; flow them back into
  the index. Plan in
  [`.paircoder/plans/review-correct.md`](.paircoder/plans/review-correct.md).

## Pipeline

```
scrape  ─►  download  ─►  ocr  ─►  clean-qc  ─►  embed  ─►  serve
   │           │           │          │            │          │
manifest    PDFs/IMGs    pages    curate QC     voyage-3   static site
(JSON,      (NAS, CAS)   .jsonl   (rules →      float16    (CF Workers)
hash-pinned)             (NAS)    Sonnet judge) payload
```

| Stage    | Status   | Output                                                        |
|----------|----------|---------------------------------------------------------------|
| scrape   | shipped  | `data/manifests/latest.json` (SHA-256-pinned, version-controlled) |
| download | shipped  | `{pdfs,images,videos}/{card_id}/{filename}` on NAS            |
| ocr      | shipped  | `ocr/{card_id}/{pages.jsonl, meta.json}` — `llm-dots`: Sonnet 4.6 primary + dots.mocr content-filter backstop; AUD via AssemblyAI |
| clean-qc | shipped  | operator-attended QC/methodology pass (rules → signal → Sonnet judge) over freshly-OCR'd pages; run in the sibling `pursue-curate` repo, then publish |
| embed    | shipped  | Voyage-3 embeddings, ~8.5MB float16 in-browser payload         |
| serve    | shipped  | Astro static build deployed to Cloudflare Workers              |

Each stage is an independent CLI verb under `pursue` and idempotent against
the manifest; re-running on an unchanged manifest is a no-op modulo
timestamps. Re-running on a new tranche only touches new entries.

See [`docs/architecture.md`](docs/architecture.md) for the full design.

## Reproducibility

The manifest is **hash-pinned and version-controlled**. From a clean clone
with the upstream CSV available, any reader can rebuild the entire index:

```bash
pursue scrape run                                        # writes manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine llm-dots   # operated engine: Sonnet 4.6 primary + dots.mocr content-filter backstop
pursue embed run --manifest data/manifests/latest.json
```

Each stage is content-addressed by `card_id = sha256(asset_url || title)[:16]`,
so partial reruns converge on the same final state regardless of order.

The CSV archive (`data/raw/csv/<sha>.csv`, content-addressed and
committed to the repo) is a forensic trail of how the source has
evolved over time. The manifest carries `csv_sha256` so upstream
changes are detectable in O(bytes-of-CSV).

## Tech stack

| Layer        | Choice                                                     |
|--------------|------------------------------------------------------------|
| Pipeline     | Python 3.12, Typer CLI, Pydantic settings                  |
| OCR engine   | `llm-dots` — Anthropic vision **Claude Sonnet 4.6** primary |
| OCR backstop | local **dots.mocr** for content-filter (HTTP 400) pages    |
| Audio (AUD)  | **AssemblyAI** transcription                               |
| Embeddings   | Voyage-3 (`voyage-3-large`)                                |
| Frontend     | Astro + Preact + Tailwind v4                               |
| Hosting      | Cloudflare Workers + Static Assets                         |
| Storage      | NAS for bulk artifacts; Git for manifests                  |

The operated corpus OCR pass — `llm-dots` (Claude Sonnet 4.6 vision per page,
with local dots.mocr backstopping content-filter pages) + Voyage-3 embeddings —
runs **~$53 for the full corpus** at current API rates (the retired
Surya-primary + auto-mode-LLM-cleanup pass was cheaper but lower quality on
degraded scans). See `docs/ocr-benchmark.md` for the breakdown.

## Storage split

The repo holds **code, manifests, and DB schema only**. Bulk artifacts live
on the NAS via two independent env vars:

| Var                     | Holds                                              |
|-------------------------|----------------------------------------------------|
| `PURSUE_DATA_ROOT`      | PDFs, images, videos, OCR output, raw CSV archives |
| `PURSUE_MANIFESTS_DIR`  | Manifest JSON (small, version-controlled)          |

In production, `PURSUE_DATA_ROOT` is the NAS mount and `PURSUE_MANIFESTS_DIR`
stays inside the repo so manifests are committed alongside the code that
produced them.

## Idempotency contract

- `card_id = sha256(asset_url || title)[:16]` — stable across re-fetches.
- Manifest carries `csv_sha256` (hash of raw CSV bytes) for cheap
  upstream-change detection.
- Each stage skips work it's already done for unchanged `card_id`s.
- The `llm-dots` engine re-OCRs a page via the local dots.mocr backstop only
  when Sonnet's output filter 400s it; previously-OCR'd pages are not re-billed.

## Repo layout

```
pursue-index/
├── src/pursue_index/
│   ├── scrape/          # CSV fetch + parse + manifest
│   ├── download/        # Asset retrieval, content-addressable storage
│   ├── ocr/             # OCR pipeline (llm-dots: Sonnet 4.6 primary + dots.mocr backstop) → pages.jsonl
│   ├── embed/           # Voyage-3 embeddings + in-browser payload
│   ├── index/           # SQLAlchemy models for forensic ingest (optional)
│   ├── cli/             # Typer CLI (`pursue`)
│   └── config/          # Pydantic settings (env-driven, PURSUE_* prefix)
├── web/                 # Astro + Preact + Tailwind v4 frontend
├── worker/              # Cloudflare Worker — chat, retrieve, and self-hosted PDFs
├── tests/               # unit + integration
├── scripts/             # bootstrap, ops helpers, benchmark runners
├── docs/                # architecture, benchmark, runbooks, launch comms
├── data/manifests/      # hash-pinned, version-controlled
└── pyproject.toml
```

## Quickstart (developers)

Requires Python 3.12+, an Anthropic API key (the operated `llm-dots` engine's
Sonnet 4.6 vision pass is API-only), and a Voyage AI API key (for embeddings).

The `llm-dots` content-filter backstop (local **dots.mocr**) needs its own
**isolated venv** — dots.mocr's dependencies conflict with the main install.
Create that venv separately and point `PURSUE_DOTS_PYTHON` at its `python`; when
it is unset the backstop cannot run and content-filtered pages will fail. (The
retired Surya engine also needed an NVIDIA GPU + CUDA toolkit; not operated.)

```bash
# Bootstrap a venv and install
make install

# Copy and edit config
cp .env.example .env
$EDITOR .env   # at minimum: PURSUE_DATA_ROOT, ANTHROPIC_API_KEY, VOYAGE_API_KEY, PURSUE_DOTS_PYTHON

# Run the pipeline
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine llm-dots   # operated engine: Sonnet 4.6 primary + dots.mocr content-filter backstop
pursue embed run --manifest data/manifests/latest.json

# Build and preview the site
cd web && npm install && npm run dev
```

## Status

Public. Site is live at [pursueindex.com](https://pursueindex.com),
the full pipeline (scrape → download → OCR → embed → serve) has run
end-to-end against PURSUE Releases 01–03 (294 cards across 7 agencies),
and the chat interface is open.

## License

Source documents are works of the U.S. Government and are in the public
domain. The OCR transcripts derived from them carry no additional copyright
claim — they are mechanically generated from public-domain originals.

The index code and this site are licensed under the
[Apache License, Version 2.0](LICENSE). Copyright © 2026
[BPS AI Software, LLC](https://bpsaisoftware.com). See [NOTICE](NOTICE)
for third-party attributions.

If you cite this work in academic or journalistic context, see
[`/cite`](https://pursueindex.com/cite) for the canonical format
(includes BibTeX). Pin the manifest CSV SHA-256 in your citation —
that's the load-bearing reproducibility claim.

For reproducing the OCR layer specifically (the only pipeline stage
whose regeneration cost is in the tens of dollars), see
[`docs/runbooks/ocr-cache-reproducibility.md`](docs/runbooks/ocr-cache-reproducibility.md).

## Built with

Powered by [PairCoder](https://paircoder.ai) — the AI-augmented pair
programming framework that ran the full pipeline: corpus scrape, OCR
benchmark, vector embeddings, chat interface, security audit, and
launch comms — orchestrated through specialized agents with
test-driven development at each stage.

## Contributing

Issues from existing GitHub users are welcome — bugs, OCR-transcript
corrections against specific pages, methodology questions. The plan
for the full review-and-correct workflow lives in
[`.paircoder/plans/review-correct.md`](.paircoder/plans/review-correct.md).
