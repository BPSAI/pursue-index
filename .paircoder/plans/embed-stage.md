---
id: embed-stage
type: feature
status: shipped
created: 2026-05-08
shipped: 2026-05-08
shipped_in: [5eaec62, 64e75cc, b7bd864, d67eb63, 7d19c6a]
depends_on: [ocr-benchmark]
---

> **Shipped 2026-05-08.** New `src/pursue_index/embed/` module with
> `pipeline.py` (orchestration), `voyage.py` (Voyage-3 adapter, lazy
> import), `openai.py` (stub seam), `store.py` (on-disk format helpers).
> CLI: `pursue embed run --manifest …` with cost guardrails (defaults
> to $1 cap, override with `--cost-cap-usd`). Output at
> `{data_root}/embeddings/{model_id}/{vectors.bin, index.json}` per the
> plan; idempotent on `(card_id, page, model_id, text_sha)`.
> `scripts/build_embed_data.py` packs to float16 for the in-browser
> payload (`web/public/data/{embeddings.bin, embed_index.json}`).
> 12 new unit tests; idempotency confirmed end-to-end on the live
> 4,153-page corpus with a fake-embedder (132 KB binary in 0.4s; second
> run was a complete no-op).
>
> **Awaiting:** ~~`VOYAGE_API_KEY` set in `.env` to run the live pass.~~
> ~~Estimated cost ~$0.13 for the full corpus per the plan estimate.~~
> ~~Real Voyage-3 binary projected at ~8.5 MB (under the 10 MB threshold)~~.
>
> **Live run completed 2026-05-09:** 4,119 pages × 1024 dims, 1.75M
> tokens, **$0.11 actual spend** (within projection). 17 MB on NAS,
> **8.04 MB float16 in-browser payload**. 34 pages were dropped at the
> input layer because their OCR text was empty/whitespace-only — the
> auto-mode pass left some near-blank scans with no usable content.
> Filter shipped in `embed/store.py:_read_card_pages`; regression
> test pins the contract.
>
> Voyage free tier rate-limits gated the first attempt; user added a
> payment method which lifted the cap. No surprise; documented in the
> agent-memory `feedback_voyage_free_tier.md`.
>
> **Note re: dependency order.** The plan listed this as
> `depends_on: [ocr-benchmark]`, meaning we'd embed the *highest-quality*
> OCR output. Pragmatic call: shipped against current Tesseract output
> so chat-interface can move ahead. Re-run is cheap once Surya/LLM
> output replaces the Tesseract pages — idempotency keys mean only
> changed pages re-embed.

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
