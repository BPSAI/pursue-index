---
id: ocr-gpu-surya
type: feature
status: shipped
created: 2026-05-08
shipped: 2026-05-08
shipped_in: [41ef7b1, f521f93, 44aa0a6, decd40d, f3b5e7b]
---

> **Shipped 2026-05-08.** Engine adapter at `src/pursue_index/ocr/surya.py`,
> wired through `_run_engine` in `pipeline.py`, exposed via
> `PURSUE_OCR_ENGINE=surya` and `pursue ocr run --engine surya`. Live
> smoke on the 40-page FBI HQ-83894: 56.76s @ 93.90% conf vs Tesseract's
> 106.19s on the same file (~1.87× faster, materially higher confidence).
> 23/23 tests pass. `transformers<5` pinned in `[gpu]` extra.
>
> **Open follow-ups (small chores, tracked in this plan):**
>
> 1. `pursue ocr run --force` — the idempotency check skips cards with
>    existing `meta.json`, which prevents re-OCR with a different engine.
>    The benchmark plan (`ocr-benchmark.md`) needs this. Either a
>    `--force` flag or `--engine` causing a separate `meta-{engine}.json`
>    sidecar so engines stack.
> 2. Surya output sometimes contains `<b>...</b>` tags from
>    `math_mode=True` (Surya's default). Decide whether to disable
>    `math_mode` for this corpus or strip in-output downstream of
>    `ocr_image`. The corpus has essentially no math, so disabling is
>    probably right.
> 3. Full Surya re-OCR of all 116 PDFs (blocked on #1).

# OCR engine: Surya on the 5090

## Why

Tesseract v1 is CPU-only. The local 5090 sits idle during OCR runs. On long
or low-quality scans, modern transformer-based OCR
([Surya](https://github.com/VikParuchuri/surya)) typically outperforms
Tesseract on text quality *and* runs 5–20× faster on a 5090.

The current FBI corpus has several scanned multi-hundred-page archives where
Tesseract takes 10+ minutes per document; Surya should bring those under a
minute each.

## Scope

1. Add `surya-ocr` (or equivalent) as an optional dep behind a `[gpu]` extra.
2. Implement `ocr/surya.py` with the same `(image, dpi) -> (text, confidence)`
   contract as `ocr/pipeline.py:ocr_image`, so it slots into the existing
   `_run_engine` seam.
3. Add `PURSUE_OCR_ENGINE=surya` and route in `ocr_card`.
4. Decide whether to re-OCR existing Tesseract output. Since `meta.json`
   already records engine + confidence, a `--force --engine surya` rerun
   should be straightforward.

## Out of scope (for v1 of this plan)

- LLM fallback — separate plan (`ocr-llm-fallback.md`).
- Mixed-engine workflows (per-page engine selection) — only after both Surya
  and the LLM path land.

## Acceptance

- `pursue ocr run --manifest data/manifests/latest.json --engine surya`
  produces `pages.jsonl` with `engine: "surya"` per page.
- A/B comparison on ~5 representative PDFs (one clean typewriter, one faded
  FBI scan, one multi-column report, one redacted form, one long debriefing)
  shows Surya at higher mean confidence and lower wall-clock than Tesseract.
- arch check clean; existing Tesseract tests untouched.
