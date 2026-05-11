---
id: llm-cleaned-pilot-spotcheck
type: chore
status: ready
created: 2026-05-11
priority: high
depends_on: [llm-cleaned-reading-text]
---

# LLM-cleaned pilot spot-check checklist

## When to use

After `pursue clean run` completes the 30-card pilot (or hits the
`--budget-usd 0.75` cap), **before** running the full corpus pass.

The pilot output lives in per-card sidecar JSONLs on the NAS, alongside
the existing OCR transcripts. Each cleaned row carries provenance:
`model_id`, `prompt_sha256`, `input_sha256`, `output_sha256`,
`generated_at`. Skip rows carry the same provenance plus a
`cleanup_skipped` reason: `empty_input`, `length_divergence`, or
`content_filter`.

The pilot's job is **not** to clean every page perfectly. It is to give
the operator enough surface area to make a go/no-go decision on the
full corpus run.

## The five pages to spot-check

Pick one page from each of these classes — diversity matters more than
volume:

1. **FBI carbon, low-OCR-confidence page.** Worst-case scenario for the
   raw transcript; the cleanup pass is supposed to help here the most.
   Candidate: any page from card `7d58f0cac741650a` (FBI 62-HQ-83894
   Section 10) where the raw OCR text reads as dense gibberish.

2. **Modern MISREP, clean OCR page.** Best-case for the raw transcript;
   the cleanup pass should change very little. Candidate: any page
   from a `d8e5687dc870892d` (D23) or DOW MISREP card where the raw
   text already reads cleanly.

3. **Redaction-heavy page.** Document with visible black-bar redactions.
   The cleanup pass must preserve the redaction markers (`[REDACTED]`,
   `■■■`, or whatever the OCR rendered) — it must not "fill in" the
   blanks with hallucinated detail.

4. **Image-caption page.** A page whose primary content is a photograph
   or sketch with a caption. The cleanup pass should preserve the
   caption verbatim and not invent description of the image content
   (that's `pursue-vision-augment`'s job, not the cleanup pass).

5. **Page adjacent to a skip row.** Find a `content_filter` or
   `length_divergence` skip row in any card's sidecar, then look at
   the cleaned versions of the immediately preceding and following
   pages. Are they still coherent on their own, or did the cleanup
   pass produce something that only makes sense if you assume the
   skipped page's content?

## Per-page checklist

For each of the five pages, open the cleaned sidecar and the raw OCR
side-by-side and answer all eight questions. The default answer for
ship-readiness is "all eight pass."

### 1. Length sanity

- [ ] Ratio of `len(cleaned)` to `len(raw)` is between 0.8 and 1.5.

Notes:
- Below 0.8 means the cleanup pass dropped content (may be acceptable
  if it was clearly OCR garbage, but verify).
- Above 1.5 should already have been caught by the `length_divergence`
  guardrail (threshold ~2.0); if it landed in the sidecar anyway, the
  threshold needs revisiting.

### 2. No hallucinated factual detail

- [ ] The cleaned text contains no names, dates, places, or events
      that don't appear in the raw OCR.

Notes:
- This is the highest-stakes failure mode. A hallucinated proper noun
  in a government archive is a credibility ender.
- Look especially for: dates (the model may "round" partial dates),
  proper names (the model may fill in initials), unit/aircraft
  designators (easy to confuse), and locations.

### 3. Voice match

- [ ] Cleaned text reads in the same register as the source document
      (terse government memo, formal report, etc.).

Notes:
- Failure mode: the model "improves" prose toward AI-marketing voice
  ("This document highlights..." / "It is important to note that...").
- The cleanup pass should produce text that could plausibly have been
  typed by the original report's author.

### 4. OCR-artifact handling

- [ ] Bracketed editorial notes preserved (e.g. `[illegible]`,
      `[stamp]`, `[redacted]`).
- [ ] Garbled runs that are recognizable as OCR failures (not source
      text) are either preserved verbatim or wrapped in a bracketed
      note — **never silently rewritten into plausible-but-invented
      text**.

Notes:
- This is the boundary between "cleaning" and "fabricating." The
  cleanup pass is allowed to fix `Iieutenant` → `Lieutenant`. It is
  not allowed to fix `XXXXX-redacted-name-XXXXX` → an invented name.

### 5. Verbatim quotability

- [ ] If a journalist quoted the cleaned text and the quote turned out
      to differ from the raw transcript, the difference would be
      defensible as OCR cleanup (e.g. spacing, common letter
      substitutions, line-break normalization) — not as paraphrase.

Notes:
- Operator gut-check: if you were citing this in a published piece,
  would you cite the cleaned text or the raw transcript? If the
  cleaned text wouldn't pass diligence, it isn't ready to ship.

### 6. Page-boundary fidelity

- [ ] The cleaned text describes only this page's content, not the
      adjacent pages' content. No "continued from previous page"
      synthesis. No anticipatory references to the next page.

Notes:
- The cleanup prompt should isolate each page; if the model is
  pulling context across pages, the per-page-cleaning premise is
  broken.

### 7. Provenance row populated

- [ ] `model_id`, `prompt_sha256`, `input_sha256`, `output_sha256`,
      and `generated_at` are all present on the row.

Notes:
- Idempotency depends on this. If any field is missing, re-running
  the pipeline will either skip a page it shouldn't or re-spend on a
  page it already cleaned.

### 8. Skip rows look right (only for page 5 adjacency check)

- [ ] The skip row carries a recognized `cleanup_skipped` reason.
- [ ] The skip row carries the same provenance fields as a cleaned
      row (so re-runs are idempotent on the skip itself).
- [ ] The reader-mode UI on the live site can render the skip
      gracefully (shows "Cleaned text not available for this page —
      reason: `<reason>`" or similar, not a blank or error).

## Aggregate ship-readiness

After all five pages are checked:

- **All 40 checks pass:** go. Run the full corpus pass.
- **1-3 minor checks fail (e.g. one voice-match call, one
  length-ratio outlier):** discuss with operator; likely still go,
  with the failure documented as a known limitation in `/methodology`.
- **Any hallucination (check 2) or fabrication (check 4) failure on
  any page:** no-go. Iterate on the cleanup prompt before the full
  run. A single hallucinated fact in 4,153 pages is a credibility
  ender; the pilot is supposed to catch this.
- **Provenance failures (check 7):** no-go regardless of severity.
  Re-running the pipeline won't converge without complete provenance.

## Notes on this pilot's specific cards

The 30-card pilot was selected to span the corpus's failure-mode
diversity: FBI carbons, modern DOW MISREPs, NASA technical reports,
mixed image/text cards. The card `7d58f0cac741650a` (FBI 62-HQ-83894
Section 10) is the worst-case card and the one where the runner
crashed last night on page 88 (content filter); a clean spot-check on
multiple pages of this card is a good proxy for the corpus's hardest
sub-population.

If the budget cap hits before all 30 cards process, the spot-check
still proceeds — just pick the five pages from whatever did complete.
The point is signal, not coverage.

## After the spot-check

If go: run `pursue clean run --manifest data/manifests/latest.json
--budget-usd 25.00` for the full corpus pass, then
`python scripts/build_pages_cleaned.py` to produce the deployable
asset, commit, and push.

If no-go: open an issue documenting the failure mode, iterate on the
cleanup prompt (likely in `src/pursue_index/clean/prompts.py` or
similar), and re-pilot. The prompt-version bump will invalidate the
idempotency cache and re-run only the affected pages.
