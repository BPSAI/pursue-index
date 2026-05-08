---
id: ocr-llm-fallback
type: feature
status: shipped
created: 2026-05-08
shipped: 2026-05-08
shipped_in: [f68d368, 2d79b54, 4d31810, bb7c021, caf720f, 9b8029e]
---

> **Shipped 2026-05-08.** Engine adapter at `src/pursue_index/ocr/llm.py`
> wires Anthropic vision behind `engine="llm"` and `engine="auto"`.
> Auto-mode runs primary (surya|tesseract) per page and re-OCRs any
> page with `confidence < PURSUE_OCR_LLM_THRESHOLD` via the LLM. System
> prompt cached via `cache_control=ephemeral`; per-image SHA-256
> response cache lives at `{data_root}/ocr/.llm-cache/`. Token usage
> logged via `ocr.llm.usage`. `pursue ocr run --force` bypasses
> idempotency. Live smoke on FBI HQ-83894 (15 pp, mixed-quality
> faded scan): 9 pages re-OCR'd, ~16k input + 3.1k output tokens
> (~$0.03 at Haiku-4.5, ~$0.10 projected at Sonnet-4.6); page-1 cover
> sheet went from 4 lines of garbage to a complete transcription.

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
