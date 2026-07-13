# Project Context

## What Is This Project?

**Project:** pursue-index
**Live:** <https://pursueindex.com>
**Source:** <https://www.war.gov/UFO/>
**Code:** <https://github.com/BPSAI/pursue-index> (Apache-2.0)

A citable, full-text + semantic-search interface to the U.S. Department of
War's PURSUE (Presidential Unsealing and Reporting System for UAP Encounters)
document releases. The DOW publishes new tranches every few weeks; the
pipeline is designed to re-run incrementally against each refresh of the
source CSV.

## Pipeline

```
scrape  →  download  →  ocr  →  clean-qc  →  embed  →  serve
  │           │          │         │          │         │
  manifest    PDFs/IMGs  text    LLM-judge   voyage    static site +
  (JSON,      /A-V       .jsonl  QC pass     float16   Cloudflare Worker
  hash-pinned)(NAS,CAS)  (NAS)   (curate)    payload   (RAG chat backend)
```

AUD (audio) cards branch off `ocr` into an AssemblyAI transcription path;
A/V is self-served from our R2 (DVIDS is the cited provenance source, not
the playback path). `clean-qc` is the operator-attended LLM-judge QC stage
run in pursue-curate over freshly-OCR'd pages before embed/publish.

Each stage is independently runnable via the `pursue` CLI and idempotent
against a content-hashed manifest. Re-running on an unchanged manifest is
a no-op modulo timestamps.

## Repository Structure

```
pursue-index/
├── .paircoder/                 # PairCoder system files
├── .claude/                    # Claude Code integration (skills, hooks)
├── src/pursue_index/
│   ├── scrape/                 # CSV fetch (curl_cffi w/ Chrome TLS) + manifest
│   ├── download/               # Asset retrieval (httpx + tenacity, content-addressable)
│   ├── ocr/                    # llm-dots: Sonnet 4.6 primary + dots.mocr backstop; engine seam
│   ├── embed/                  # Voyage-3 embeddings + in-browser payload
│   ├── novelty/                # Cosine top-1 vs reference index → disclosure status
│   ├── index/                  # SQLAlchemy models (forensic ingest, optional)
│   ├── cli/                    # Typer CLI (`pursue`)
│   └── config/                 # Pydantic settings (env-driven, PURSUE_* prefix)
├── web/                        # Astro + Preact + Tailwind v4 frontend
├── worker/                     # Cloudflare Worker (chat backend, retrieve/SSE)
├── tests/                      # unit + integration (pytest + node:test)
├── scripts/                    # bootstrap, ops helpers, build_search_data
├── docs/                       # architecture, benchmark, launch comms
├── data/manifests/             # hash-pinned, version-controlled
└── pyproject.toml
```

## Tech Stack

- **Language:** Python 3.12 (pipeline) + JavaScript (worker, web)
- **CLI:** Typer + Rich
- **Settings:** pydantic + pydantic-settings (env-driven, `PURSUE_*` prefix)
- **HTTP:** httpx + tenacity (downloads); curl_cffi w/ Chrome TLS (scrape)
- **OCR:** llm-dots (Sonnet 4.6 per-page primary + local dots.mocr content-filter backstop); AUD via AssemblyAI
- **Embeddings:** Voyage-3 (`voyage-3-large`, 1024d, float16 in-browser)
- **Frontend:** Astro 6 + Preact + Tailwind v4 (CSS-first @theme tokens) + MiniSearch
- **Worker:** Cloudflare Workers + Static Assets, KV namespace `CHAT_KV`
- **Tests:** pytest (Python) + node:test (worker)
- **Lint/Type:** ruff + mypy (strict)

## Data Source

The DOW PURSUE page is a DataTables widget rendering a single CSV:
`https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-data.csv`
(rotated twice: from `uap-csv.csv` to `uap-release001.csv` on 2026-05-12,
then consolidated to `uap-data.csv` on 2026-05-22 when Release 02 landed).
We fetch that CSV directly via `curl_cffi` with Chrome TLS impersonation
(Akamai fingerprinting blocks naive httpx). DOW now keeps every release in
one mutating canonical file rather than splitting each tranche under its
own filename.

CSV columns we consume: Redaction, Release Date, Title, Type (PDF/VID/IMG),
Video Pairing, PDF Pairing, Description Blurb, DVIDS Video ID, Video Title,
Agency, Incident Date, Incident Location, PDF | Image Link, Modal Image.

## Storage Split

Two independent paths so manifests stay in the repo and bulk data goes to NAS:

| Path                    | Holds                                               |
|-------------------------|-----------------------------------------------------|
| `PURSUE_DATA_ROOT`      | PDFs, images, videos, OCR output, raw CSV archives  |
| `PURSUE_MANIFESTS_DIR`  | Manifest JSON (small, version-controlled)           |

In production, `PURSUE_DATA_ROOT` points at the NAS mount on the dev NAS
(currently the project's NAS data root). Manifests stay under `./data/manifests`
and are committed.

## Idempotency

`card_id = sha256(asset_url || title)[:16]`. The manifest carries
`csv_sha256` so upstream changes are detectable in O(bytes-of-CSV).
The llm-dots engine re-OCRs a page via the local dots.mocr backstop only when
Sonnet's content filter 400s it; previously-OCR'd pages are not re-billed.

## Key Constraints

| Constraint        | Requirement                                              |
|-------------------|----------------------------------------------------------|
| **Test Coverage** | 80% target                                               |
| **Architecture**  | `bpsai-pair arch check` enforces 400-line/50-fn limits   |
| **Secrets**       | Never commit `.env` (tracked: `.env.example`)            |
| **Source data**   | Public domain US Government works (17 USC §105)          |
| **Code license**  | Apache-2.0; © 2026 BPS AI Software, LLC                  |
| **Cost ceiling**  | Full pipeline pass < $2 at current API rates             |
| **Worker spend**  | $100/day global cap; 5 chats/IP/24h on anonymous tier    |

## Architecture Principles

1. **Stage isolation** — each pipeline stage is independently runnable and emits
   structured JSON; PairCoder enforces stage contracts.
2. **Code/data split** — repo holds code + manifests + DB schema; NAS holds blobs.
3. **Idempotent re-runs** — content-hashed manifest enables cheap diffs.
4. **Test-driven** — write failing tests first; see `implementing-with-tdd` skill.
5. **Citation discipline** — every answer in chat carries `[card_id:page]`
   citations that resolve to a primary-source page; off-corpus questions
   abstain rather than hallucinate.

## How to Work Here

1. Read `.paircoder/context/state.md` for current plan/task status.
2. Check `.paircoder/capabilities.yaml` for available actions.
3. Follow the active skill for structured work (see `.claude/skills/`).
4. Update `state.md` after completing significant work.
5. Run `bpsai-pair arch check <path>` before completing any code task.

## Key Files

| File                                     | Purpose                                |
|------------------------------------------|----------------------------------------|
| `.paircoder/config.yaml`                 | Project configuration                  |
| `.paircoder/context/state.md`            | Current status and active work         |
| `docs/architecture.md`                   | Canonical architecture doc             |
| `docs/ocr-benchmark.md`                  | OCR engine bake-off + numbers          |
| `src/pursue_index/scrape/csv_fetcher.py` | CSV fetch entry point (curl_cffi)      |
| `src/pursue_index/cli/commands.py`       | Typer CLI surface                      |
| `worker/index.js`                        | Worker entry (CORS, security, dispatch) |
| `worker/chat.js`                         | RAG chat orchestrator                  |
| `worker/retrieve.js`                     | Voyage query embed + cosine top-k      |
| `web/src/layouts/Base.astro`             | Site nav + meta defaults               |
| `pyproject.toml`                         | Dependencies + tool config             |
| `.env.example`                           | Env var contract                       |
