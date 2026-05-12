---
id: llm-cleaned-reading-text
type: feature
status: shipped
created: 2026-05-09
priority: medium
depends_on: [embed-stage, reader-mode]
---

# LLM-cleaned reading text (`Cleaned` overlay)

## Why

Reader mode fixed presentation; the underlying OCR is still raw — broken
hyphenation, column-detection scrambles, redaction-boundary glitches. The
r/DataHoarder critique ("harder to actually read through the data than the
official page") is now a tractable cleanup problem, not a typography one.
This plan adds a third presentation layer — `Raw / Reader / Cleaned` — where
Cleaned is an LLM pass that fixes obvious OCR errors without changing
meaning. Always opt-in. Always attributed. **Raw stays canonical.**

## Storage: Option C (separate `pages-cleaned.json`)

A bloats `pages.json` (already 7.1 MB) by roughly 100% on a feature most
visitors won't toggle. B fits the NAS pipeline shape but doesn't address
deployment. C — a sibling `web/public/data/pages-cleaned.json`, lazy-loaded
only when the toggle flips — keeps un-augmented users on the existing payload
and makes the cleanup asset independently versionable. Pair it with Option A
on the NAS side: per-card `pages_cleaned.jsonl` sidecars feed the build step
that produces the deployed mirror. Idempotency keys on disk; lazy mirror in
the browser.

## Provenance

Each cleaned page row carries: `model_id`, `prompt_sha256`, `input_sha256`,
`output_sha256`, `generated_at`. No inline `[[CLEANED via …]]` marker in the
rendered text — markers contaminate copy-paste and chat citations. Instead, a
pinned footer below the page body in Cleaned mode: `Cleaned by Haiku-4.5 ·
raw transcript →`. The provenance tuple is exposed in the JSON so the chat
retriever can disambiguate cleaned vs raw at citation time without parsing
inline markers.

## Cost (with prompt cache)

4,153 pages × ~600 in / ~600 out tokens. Haiku-4.5 at $0.80/M in, $4/M out
→ ~$2 in + ~$10 out = **~$12 naïve**. The system prompt is per-page
identical, so `cache_control=ephemeral` on the system block cuts repeated
input tokens by ~85% after the first request in a 5-minute window. Realistic
pass: **~$8 corpus-wide**. Sonnet-4.6 would be ~$30 cached; not worth it for
a fix-obvious-errors task. Recommend Haiku, log the math, leave a Sonnet
escape hatch behind a `--model` flag for the spot-check runs.

## Pipeline

New stage `pursue clean run` (separate from `ocr run` — different rate-limit
profile, different failure modes, different cost ceiling). Reads `pages.jsonl`
per card, writes `pages_cleaned.jsonl` next to it. Idempotency key:
`sha256(input_text || model_id || prompt_sha256)` — re-cleaning the same
input with the same prompt and model is a skip. Build step
`scripts/build_cleaned_data.py` concatenates the per-card sidecars into the
deployed `pages-cleaned.json` mirror.

## Reader-mode UX

Toggle becomes 3-way: `[ Raw ] [ Reader ] [ Cleaned ]`. Cleaned reuses the
Reader prose typography — same `reformatOcrText` paragraph reflow, same
font stack — applied to the cleaned text. Footer attribution pinned below
the page body. The existing localStorage key `pursueindex.reader.mode`
extends cleanly: `loadReaderMode` already falls back to `"raw"` on any
unrecognized value, so adding `"cleaned"` to the union and the guard
(`v === "cleaned" || v === "reader" || v === "raw"`) is the entire
migration. Zero risk to existing users — old browsers with the old key see
their stored value, new option is opt-in.

When the cleaned mirror hasn't loaded yet (or 404s in dev), the Cleaned
button is disabled with a tooltip — never silently fall back to Raw and
mislabel it.

## Prompt design

System prompt, ~3 paragraphs:

> You are correcting OCR errors in a declassified government document
> page. Your only job is to fix obvious transcription mistakes the OCR
> engine made. Fix dehyphenation across line breaks, repair column-detection
> scrambles where two columns of text were interleaved into one stream, and
> normalize confused punctuation (e.g. `,` read as `.` mid-sentence). You
> may expand an obvious abbreviation only when the full form appears
> elsewhere in the same page.
>
> You must NOT paraphrase, reorder words, smooth phrasing, summarize, or
> add commentary. You must preserve `[REDACTED]` markers exactly. Preserve
> page numbers, header stamps (`TOP SECRET`, `NOFORN`), and other visual
> artifacts the OCR captured. Preserve paragraph and line structure where
> the OCR got it right.
>
> If the page is too sparse (a stamp page, a separator) or too garbled to
> clean responsibly without guessing, return the input text unchanged.
> Output JSON: `{"cleaned": "<text>", "changed": <bool>}`. No prose.

Few-shot: (1) a dehyphenation example, (2) a two-column scramble repair,
(3) a refusal on a stamp-only page returning input unchanged.

## QA

`scripts/qa_cleaned.py` produces a per-card diff report and aggregate stats:
% of pages where `cleaned == raw`, median character delta, max delta.
Pages with delta >30% are flagged into a review queue; they don't ship to
the deployed mirror until a human runs `pursue clean approve <card>/<page>`.
Extend `/diff` (page already exists for OCR-vs-source) with a `?layer=clean`
mode showing raw-vs-cleaned side-by-side. Spot-check budget: 30 cards
(~5% of corpus) before launch.

## Failure modes

- 429 mid-batch: exponential backoff, resume from last completed page —
  the idempotency key makes resume free.
- Output >30% character delta: write to sidecar with `flagged: true`,
  exclude from deployed mirror.
- Malformed JSON from model: catch, log, treat as no-change for that page.
- Anthropic refusal (rare): treat as no-change, log refusal reason.

## Disclosure

`/methodology` gets a "Reader cleanup" subsection: what cleanup is, what
it isn't, why Raw remains canonical. `/cite` gets a triple-citation guide:
when quoting a Cleaned snippet, cite the cleaning pass (model + date), the
OCR pass, and the source PDF page.

## Out of scope

Translating, table reformatting, semantic markup of redactions/stamps,
cleaning the IMAGE-DESCRIPTIONS blocks (alex-zhang42's third-party text).

## Recommendation: REFINE-FIRST

Ship the pipeline + QA harness against a 30-card pilot before the corpus
pass. The risk isn't cost (~$8) or infrastructure — it's prompt drift:
"fix obvious errors" is a fuzzy contract and the model will overreach
without a tight pilot to calibrate the few-shots. Once the pilot's
diff-review shows <2% of pages with substantive meaning changes, run the
full corpus and ship the toggle.

## Tasks (sketch)

- T?.1 Storage + provenance schema for `pages_cleaned.jsonl` (S, 20cx)
- T?.2 `pursue clean run` CLI + idempotency keying (M, 35cx)
- T?.3 Anthropic client with prompt cache + retry/backoff (S, 25cx)
- T?.4 System prompt + 3 few-shots, locked to a `prompts/clean_v1.md`
  file with sha tracked in provenance (XS, 15cx)
- T?.5 30-card pilot run + diff review checklist (S, 20cx)
- T?.6 `scripts/build_cleaned_data.py` build step + lazy loader (S, 25cx)
- T?.7 3-way toggle UI + localStorage migration + footer attribution
  (S, 25cx)
- T?.8 `/diff?layer=clean` page (S, 20cx)
- T?.9 `/methodology` + `/cite` copy updates (XS, 15cx)
- T?.10 Corpus pass + QA stats publication (S, 20cx)

Total ~220cx — fits one sprint with the pilot gate between T?.5 and
T?.10.
