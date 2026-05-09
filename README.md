# pursue-index

> A citable, full-text-searchable interface to the U.S. Department of War's
> **Presidential Unsealing and Reporting System for UAP Encounters (PURSUE)**
> document releases.

Live: **<https://pursueindex.com>** *(research preview, splash gate active)*
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

## Live now (2026-05-09)

- **Custom domain.** [pursueindex.com](https://pursueindex.com) on Cloudflare
  Workers + Static Assets, behind a research-preview splash gate.
- **Full-text search** across **4,153 OCR'd pages** spanning the 116 PDF cards
  in Release 01 of the corpus. Search runs in the browser; no server.
- **OCR pipeline.** Surya (GPU, transformer-based) primary, Anthropic vision
  LLM fallback for pages whose Surya confidence falls below threshold. The
  shipped index is **3,529 Surya pages + 624 LLM-cleaned pages**.
- **Published quality benchmark.** Five-PDF golden set covering the engine
  failure modes (clean typewriter / faded carbon / multi-column / redacted /
  long debriefing). Surya median CER **6.1%** vs Tesseract **40.4%** vs the
  LLM truth proxy. See [`docs/ocr-benchmark.md`](docs/ocr-benchmark.md) and
  [/methodology](https://pursueindex.com/methodology).
- **Tranche diff.** Every snapshot is timestamped under `csv-archive/`; the
  diff page surfaces per-card deltas when the upstream CSV changes.
- **Pages.** [/about](https://pursueindex.com/about),
  [/methodology](https://pursueindex.com/methodology), and a small set of
  curated [/finds](https://pursueindex.com/finds) entries — primary-source
  reading guides written against specific pages of specific cards.

## In flight (toward public launch)

- **Chat interface.** Retrieval-augmented Q&A over the corpus, with
  mandatory citations on every claim. Anonymous (server-funded, rate-limited)
  and BYOK (bring-your-own Anthropic key) modes share the same UI. The BYOK
  path keeps cost flat under HN-spike traffic.
- **Curated finds expansion.** More hand-authored reading guides; current
  set is intentionally small to set the editorial bar.
- **Novelty detection.** Per-page cosine similarity vs The Black Vault's
  reference UAP corpus → "previously disclosed vs new in this release"
  tagging. A citation moat for journalists tracking what's actually new.

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

Research preview. The site is reachable at pursueindex.com behind a splash
gate while the chat interface lands; the public launch flips the gate when
chat is shipped, the methodology page is locked, and the launch comms set
under [`docs/launch/`](docs/launch/) is published.

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

This is a research preview; we are not currently accepting outside
contributions. Once the gate flips, corrections will be welcomed via
GitHub issues against the manifest and OCR transcripts. The plan for
that workflow lives in [`.paircoder/plans/review-correct.md`](.paircoder/plans/review-correct.md).
