---
id: ocr-benchmark
type: feature
status: shipped
created: 2026-05-08
shipped: 2026-05-09
shipped_in: [972398e, b81eab3, 8dcb640, c4da5cc, 02b99aa, 79206a1]
depends_on: [ocr-gpu-surya, ocr-llm-fallback]
---

> **Shipped 2026-05-09.** Full Surya re-OCR of the 116-card corpus +
> A/B benchmark on a 5-card golden set + methodology report
> (`docs/ocr-benchmark.md`) + per-page JSON dump
> (`data/benchmarks/ocr-20260509T002235Z.json`).
>
> **Headline numbers (golden set, 25 pages, vs LLM-Haiku truth proxy):**
>
> | Engine | Mean conf | Median CER | Median WER | Per-page wall |
> |---|---:|---:|---:|---:|
> | Tesseract | 77.1 | 40.4% | 59.8% | 2.4s |
> | Surya | **85.3** | **6.1%** | **9.6%** | **1.9s** |
> | LLM (Haiku) | 76.8 | — | — | 7.7s |
>
> **Surya is the new default.** Median CER 6× better than Tesseract;
> 27% faster end-to-end despite running serialized on the GPU.
>
> **Auto-mode recommendation** (also shipped): 8% of Surya pages on
> the golden set fell below the 70-conf threshold; extrapolated to
> the full corpus that's ~332 LLM calls = **~$1.36 at Haiku-4.5** for
> a full clean-up pass. Recommended default: `auto:surya+llm-haiku`.
> Run when ready.
>
> Search payload (`web/public/data/pages.json`) rebuilt at 7.2 MB
> from Surya output (+36% from Tesseract 5.3 MB; Surya extracts more
> text across redactions and layout). Live on the site after the
> merge deploy.

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
