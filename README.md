# pursue-index

> A citable, full-text-searchable interface to the U.S. Department of War's
> **Presidential Unsealing and Reporting System for UAP Encounters (PURSUE)**
> document releases.

Live: **<https://pursueindex.com>**
Source: **<https://www.war.gov/UFO/>**
Code: **<https://github.com/BPSAI/pursue-index>**

---

## What this is

The DOW publishes the PURSUE corpus as a single CSV (`uap-csv.csv`) rendered
inside a DataTables widget. That's fine for browsing one record at a time.
It's useless for searching the actual contents of the documents.

`pursue-index` is the first end-to-end pipeline and reader for that corpus:

1. Snapshot the upstream CSV and pin its SHA-256 in a hash-stable manifest.
2. Fetch every referenced PDF / image idempotently into content-addressable storage.
3. OCR every PDF page through a GPU pipeline (Surya) with an LLM fallback for
   low-confidence pages, recording per-page engine + confidence in `pages.jsonl`.
4. Build an in-browser search index over the OCR transcripts.
5. Serve the result as a static site with mandatory citations on every claim.

Every record traces back to a specific page of a specific war.gov PDF.
Methodology is published. Numbers are reproducible from a clean clone.

## What's live

- **Custom domain.** [pursueindex.com](https://pursueindex.com) on Cloudflare
  Workers + Static Assets.
- **Full-text + semantic search** across **4,153 OCR'd pages** spanning the
  116 PDF cards in Release 01. MiniSearch lexical index + Voyage-3
  embeddings, both browser-side; no server. The `/search` route adds a
  faceted filter rail (agency multi-select, incident-date range,
  redacted-only) over the lexical index; filter state round-trips through
  the URL so links are shareable.
- **OCR pipeline.** Surya (GPU, transformer-based) primary, Anthropic vision
  LLM fallback for pages whose Surya confidence falls below threshold. The
  shipped index is **3,529 Surya pages + 624 LLM-cleaned pages**.
- **RAG chat with mandatory citations.** Anonymous tier (server-funded,
  5/IP/24h, $100/day budget cap) and BYOK tier (browser-direct to
  Anthropic). Both share the same UI. Off-corpus questions abstain
  rather than hallucinate; every cited claim is `[card_id:page]` and
  resolves to a primary-source page.
- **Published quality benchmark.** Five-PDF golden set covering the engine
  failure modes (clean typewriter / faded carbon / multi-column / redacted /
  long debriefing). Surya median CER **6.1%** vs Tesseract **40.4%** vs the
  LLM truth proxy. See [`docs/ocr-benchmark.md`](docs/ocr-benchmark.md) and
  [/methodology](https://pursueindex.com/methodology).
- **Tranche diff.** Every snapshot is timestamped under `csv-archive/`; the
  diff page surfaces per-card deltas when the upstream CSV changes.
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
  UMAP (`random_state=42`). 4,119 dots, color-coded by agency, pan / zoom
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
  poll detecting upstream CSV changes) is shipped in
  [`.github/workflows/poll-pursue.yml`](.github/workflows/poll-pursue.yml);
  it commits new shas and opens a `tranche-detected` issue. Layer 2
  (heavy ingest pipeline trigger) is operator-attended by design —
  GPU provisioning, cost, and content review keep auto-run off the
  table at v1.
- **Review-and-correct pipeline.** Post-launch, accept community
  corrections on OCR transcripts via GitHub issues; flow them back into
  the index. Plan in
  [`.paircoder/plans/review-correct.md`](.paircoder/plans/review-correct.md).

## Pipeline

```
scrape  ─►  download  ─►  ocr  ─►  embed  ─►  serve
   │           │            │        │          │
manifest    PDFs/IMGs    pages    voyage-3    static site
(JSON,      (NAS, CAS)   .jsonl   float16     (CF Workers)
hash-pinned)             (NAS)    payload
```

| Stage    | Status   | Output                                                        |
|----------|----------|---------------------------------------------------------------|
| scrape   | shipped  | `data/manifests/latest.json` (SHA-256-pinned, version-controlled) |
| download | shipped  | `{pdfs,images,videos}/{card_id}/{filename}` on NAS            |
| ocr      | shipped  | `ocr/{card_id}/{pages.jsonl, meta.json}` — Surya + LLM fallback |
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
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json
```

Each stage is content-addressed by `card_id = sha256(asset_url || title)[:16]`,
so partial reruns converge on the same final state regardless of order.

The CSV archive (`{data_root}/csv-archive/uap-csv-<timestamp>.csv`) is a
forensic trail of how the source has evolved over time. The manifest carries
`csv_sha256` so upstream changes are detectable in O(bytes-of-CSV).

## Tech stack

| Layer        | Choice                                                     |
|--------------|------------------------------------------------------------|
| Pipeline     | Python 3.12, Typer CLI, Pydantic settings                  |
| OCR primary  | [Surya](https://github.com/datalab-to/surya) on CUDA       |
| OCR fallback | Anthropic vision (Haiku-4.5 default; Sonnet-4.6 available) |
| Embeddings   | Voyage-3 (`voyage-3-large`)                                |
| Frontend     | Astro + Preact + Tailwind v4                               |
| Hosting      | Cloudflare Workers + Static Assets                         |
| Storage      | NAS for bulk artifacts; Git for manifests                  |

The full corpus pipeline pass — Surya OCR + auto-mode LLM cleanup on the 624
sub-threshold pages + Voyage-3 embeddings — costs **under $2** end to end at
current API rates. See `docs/ocr-benchmark.md` for the breakdown.

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
- Auto-mode OCR re-runs LLM cleanup only on pages whose primary-engine
  confidence is below threshold; previously-cleaned pages are not re-billed.

## Repo layout

```
pursue-index/
├── src/pursue_index/
│   ├── scrape/          # CSV fetch + parse + manifest
│   ├── download/        # Asset retrieval, content-addressable storage
│   ├── ocr/             # Surya + LLM-fallback pipeline → pages.jsonl
│   ├── embed/           # Voyage-3 embeddings + in-browser payload
│   ├── index/           # SQLAlchemy models for forensic ingest (optional)
│   ├── cli/             # Typer CLI (`pursue`)
│   └── config/          # Pydantic settings (env-driven, PURSUE_* prefix)
├── web/                 # Astro + Preact + Tailwind v4 frontend
├── worker/              # Cloudflare Worker for the chat backend (in flight)
├── tests/               # unit + integration
├── scripts/             # bootstrap, ops helpers, benchmark runners
├── docs/                # architecture, benchmark, runbooks, launch comms
├── data/manifests/      # hash-pinned, version-controlled
└── pyproject.toml
```

## Quickstart (developers)

Requires Python 3.12+, an NVIDIA GPU with current CUDA toolkit (for Surya),
an Anthropic API key (for the OCR LLM fallback), and a Voyage AI API key
(for embeddings).

```bash
# Bootstrap a venv and install
make install

# Copy and edit config
cp .env.example .env
$EDITOR .env   # at minimum: PURSUE_DATA_ROOT, ANTHROPIC_API_KEY, VOYAGE_API_KEY

# Run the pipeline
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json

# Build and preview the site
cd web && npm install && npm run dev
```

## Status

Public. Site is live at [pursueindex.com](https://pursueindex.com),
the full pipeline (scrape → download → OCR → embed → serve) has run
end-to-end against PURSUE Release 01, and the chat interface is open.

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
