---
id: ocr-benchmark
type: feature
status: backlog
created: 2026-05-08
depends_on: [ocr-gpu-surya, ocr-llm-fallback]
blocked_on:
  - "ocr-gpu-surya follow-up #1: --force flag or per-engine meta sidecar"
  - "ocr-llm-fallback (not yet started)"
---

> **Blocker:** the harness needs to OCR the same PDF with multiple
> engines and compare. Today, `meta.json` idempotency skips a card with
> any prior engine output. Until `pursue ocr run --force` (or per-engine
> meta files) lands, you can only benchmark a "fresh" PDF the first time.

# OCR benchmark harness

## Why

We're going to make claims about OCR quality (Surya beats Tesseract; LLM
fallback beats both on faded pages). Right now those claims are vibes.
Before we ship a public chat, we need to *prove* the quality lift on a
fixed golden set so we can publish methodology with numbers.

This is also the harness that decides which engine gets the default
slot in `auto` mode and how the LLM-fallback confidence threshold is
tuned.

## Golden set

5 PDFs, hand-selected to cover the engine failure modes:

1. **Clean typewriter** — a NASA debriefing or DOW report with crisp
   black-on-white typewritten text. Tesseract should ace this; if it
   doesn't, we have bigger problems.
2. **Faded FBI scan** — 1950s carbon-copy with low contrast and bleed.
   Tesseract historically struggles; Surya should improve; LLM should win.
3. **Multi-column government form** — 2-or-3-column layout with form
   fields. Tests reading order more than character recognition.
4. **Redacted page** — visible black-bar redactions over typed text.
   Tests how engines handle occluded regions and whether they hallucinate
   text inside them.
5. **Long debriefing** — 100+ pages, mixed quality. Stresses throughput
   and tests engine consistency across a single document.

Pick the cards by `card_id` and pin them in `tests/fixtures/ocr_golden.txt`.

## Truth set

For pages 1–5 of each golden PDF, hand-transcribe the ground truth text
(or use the LLM with explicit "transcribe verbatim, [REDACTED] for black
bars" prompt and spot-check). Store under
`tests/fixtures/ocr_truth/{card_id}/page-{n}.txt`.

This is one-time grunt work. Once it exists, every engine gets scored
against it automatically.

## Metrics

Per page, per engine:

- **CER** — character error rate vs ground truth (Levenshtein / len)
- **WER** — word error rate
- **Confidence** — engine's own self-reported score
- **Wall-clock** — seconds end-to-end for that page
- **$ cost** — fixed for free engines, computed from token usage for LLM

Per engine, aggregate:

- Mean / median CER and WER
- p95 CER (tail behavior)
- Total wall-clock and cost across the golden set

## Output

`scripts/run_ocr_benchmark.py`:

1. For each engine in `[tesseract, surya, llm]`, run all golden pages.
2. Compute metrics against the truth set.
3. Write `data/benchmarks/ocr-{timestamp}.json` (committed) with full
   per-page detail.
4. Render a Markdown summary at `docs/ocr-benchmark.md` with the latest
   numbers and a delta from the previous run.

A `/benchmark` route in the web UI surfaces this for public visibility on
launch — methodology transparency is a feature, not an internal artifact.

## Acceptance

- Re-running the harness is a single command and reproducible.
- The Markdown summary makes it obvious which engine wins which scenario.
- We can answer "how accurate is the OCR?" with a number and a method,
  not a hand-wave.

## Open questions

- Truth-set transcription via LLM vs human. LLM-only feels circular;
  human spot-checks of LLM transcriptions feels reasonable.
- Engine-confidence scoring for the LLM fallback (a real number, not
  always 1.0). Self-rated, agreement-pass with a smaller model, or
  fixed nominal.
