---
id: review-correct
type: feature
status: backlog
created: 2026-05-08
depends_on: [ocr-benchmark]
---

# Review + correct pipeline

## Why

Even after Surya + LLM fallback, some pages will have errors that matter
(proper nouns, dates, redaction boundaries). For a publicly-cited corpus,
we want a pathway to:

1. Detect pages most likely to contain errors.
2. Surface them for review.
3. Apply corrections that flow back into the search index and chat
   retrieval.

Done right, this is *the* differentiator vs "ChatGPT can read PDFs too."
We're publishing a curated corpus, not a passthrough.

## Detection signal

A page is a review candidate if any of:

- Engine confidence below threshold (per-engine tuned in benchmark).
- Cross-engine disagreement: Surya and LLM produce text with high
  Levenshtein distance.
- Heuristic flags: extremely short text on a non-blank page,
  non-printable character density above threshold, gibberish-N-gram
  detector trips.

Score each page, write `review_priority` into `meta.json`. Top-K page
queue is what reviewers see.

## Reviewer surface

A `/review` route (auth-gated, not public) showing one page at a time:

- Original PDF page rendered alongside the OCR output.
- Diff view between engines so reviewer sees the disagreement.
- Plain-text editor for corrections.
- Save → writes to `data/corrections/{card_id}/page-{n}.txt` and bumps
  a `corrected_at` timestamp.

## Agent-driven mode

Most pages don't need a human. An agent loop reads the candidate queue,
fetches the page image, asks a vision LLM to "transcribe verbatim,"
compares to current OCR text, applies corrections that don't change
substantive meaning. Logs all changes for post-hoc audit.

Human reviewers handle the agent-flagged-uncertain cases: claims about
proper nouns, dates that don't parse, redaction boundary debates.

## Corpus impact

Corrections are first-class:

- `pages.jsonl` rows gain a `corrected: bool` flag and a
  `correction_source: "agent" | "human" | null` field.
- Embed stage re-embeds corrected pages.
- Chat retrieval prefers corrected text when present.
- The /benchmark page tracks correction rate over time as a quality metric.

## Acceptance

- Review queue is sorted by `review_priority` and consumes from top.
- Saving a correction triggers re-embedding for that page (idempotent).
- Corrections are committed under `data/corrections/` and visible in
  diff history.
- An agent loop closes the loop on the bottom 60% of the queue without
  human review while logging confidence rationale.

## Open questions

- Editor surface: full prose editor, or word-level inline corrections
  with a left-original / right-corrected diff? Latter is faster but harder
  to build.
- Audit trail: do we store the pre-correction version? (yes, for
  transparency — keep `pages.jsonl.original` per-card).
- Public visibility: should the `/review` history be public? Probably
  yes — it strengthens the methodology story.
