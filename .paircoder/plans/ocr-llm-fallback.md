---
id: ocr-llm-fallback
type: feature
status: backlog
created: 2026-05-08
---

# OCR fallback: LLM vision extraction

## Why

The original architecture spec called for Azure Document Intelligence as the
high-quality OCR fallback. Azure DI is OCR-1.0 territory — you wire up a
specific extraction model, manage endpoints, pay per-page, and it doesn't
materially outperform a frontier vision LLM on hard pages anyway.

Anthropic and OpenAI vision models can do page-level extraction directly
from an image, with much better handling of:

- Faded carbon-copy typewriter pages
- Multi-column government forms
- Hand-stamped redactions
- Marginalia and handwritten annotations
- Tables and figures (LLM gives structured output)

Cost is in the same ballpark per-page (frontier-vision tokens vs Azure DI
$1.50/1k), and integration is a single API call instead of a model-deploy
workflow.

## Scope

1. Implement `ocr/llm.py` with the same `(image) -> (text, confidence)`
   contract as `ocr/pipeline.py:ocr_image`. Confidence is harder for LLMs —
   we'll use a self-reported score from a structured-output prompt or fall
   back to a fixed nominal value.
2. Wire `PURSUE_OCR_ENGINE=auto` to the actual auto-fallback logic: run
   primary engine first, retry pages below threshold via LLM.
3. Ship behind an optional `[llm]` extra; default install stays Tesseract-only.
4. Keep prompt + provider config in `pursue_index/config/settings.py` so we
   can flip Anthropic ↔ OpenAI without code changes.

## Out of scope

- Document-level reasoning (summarization, entity extraction) — that's the
  ingest stage's job, not OCR. OCR's contract is "image → text".
- Vision-only extraction for image cards (NASA Apollo stills, etc.) —
  separate concern, eventually a `vision/` stage.

## Open questions

- Which provider as default? Anthropic gives us cleaner control over output
  format via `prefill` and `stop_sequences`. OpenAI's `gpt-4o` may be
  cheaper per-page on long inputs.
- How to encode confidence? Options: model self-rates, second-pass
  agreement check, fixed `1.0` (since the LLM is presumed-best path).
- Caching strategy for re-runs — image content-hash → response cache.

## Acceptance

- `pursue ocr run` with `engine=auto` re-OCRs pages where Tesseract mean
  confidence < threshold (e.g., 70) via the LLM, recording `engine: "llm-{provider}"`.
- Per-page cost is logged so we can budget large runs.
- Cache prevents duplicate spend on idempotent re-runs.
