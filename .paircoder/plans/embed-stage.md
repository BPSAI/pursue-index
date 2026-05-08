---
id: embed-stage
type: feature
status: backlog
created: 2026-05-08
depends_on: [ocr-benchmark]
---

# Pipeline stage: pursue embed

## Why

Chat needs retrieval. Retrieval needs vectors. We add a new pipeline
stage between `ocr` and `serve` that produces page-level embeddings,
written to a content-addressed file the chat backend reads.

Idempotency contract matches the rest of the pipeline: re-running on an
unchanged manifest is a no-op; corrections trigger targeted re-embed.

## Scope

1. `pursue embed run --manifest data/manifests/latest.json` — embeds
   every `pages.jsonl` page that doesn't already have a current
   embedding.
2. Output convention:
   ```
   {data_root}/embeddings/{model_id}/
     vectors.bin     # contiguous float32 [N, D] little-endian
     index.json      # {model_id, dim, n, pages: [{card_id, page, offset}], created_at}
   ```
3. Embedding model: **Voyage-3** (default) — strong on document semantic
   search, $0.06 / 1M tokens. Configurable to OpenAI text-embedding-3-large.
   Model name + version baked into output dir so multiple embeddings
   coexist for A/B retrieval testing.
4. Chunking: page-level. The OCR stage already produced page boundaries;
   they're a clean retrieval unit. Sub-page chunking is deferred until
   we observe retrieval failures from page-length context.
5. Idempotency: page-level skip if `(card_id, page, model_id, text_sha)`
   matches a prior run.

## Web build integration

`scripts/build_search_data.py` already produces `pages.json` for
in-browser MiniSearch. Add a sibling
`scripts/build_embed_data.py` that produces:

- `web/public/data/embeddings.bin` — packed float16 [N, D] (smaller than
  float32, lossy but fine for cosine retrieval).
- `web/public/data/embed_index.json` — per-vector mapping back to
  `(card_id, page)`.

In-browser semantic retrieval becomes possible; only the LLM call needs
a backend.

## Cost estimate

4,153 pages × ~500 tokens average × $0.06/M = **~$0.13 to embed the full
corpus** with Voyage-3. Negligible. Budget cap in code anyway in case
pagecount jumps with future tranches.

## Acceptance

- `pursue embed run` writes a populated `vectors.bin` + `index.json`.
- Re-running on unchanged manifest is a no-op.
- Updating a single corrected page re-embeds only that page.
- Cosine-similarity retrieval against a trivial query in a unit test
  returns the expected page (e.g., query "Roswell" → Roswell-related
  pages in top-5).

## Open questions

- Voyage vs OpenAI as default. Voyage's `voyage-3` is currently best on
  retrieval benchmarks for this kind of long-document corpus, but the
  OpenAI ecosystem is more familiar.
- Float16 vs float32 for the in-browser shipped embeddings. Recall delta
  on a typical query is < 1%; size delta is 50%. Ship float16.
- Sub-page chunking: page-level is fine for retrieval *to* the LLM
  context, but for highlighting we might want sentence-level. Defer.
