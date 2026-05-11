---
id: clean-quality-review
type: feature
status: backlog
created: 2026-05-11
priority: medium
depends_on: [llm-cleaned-reading-text]
---

# LLM-cleaned text quality review engine

## Summary

Add an **LLM-judge layer** that auto-grades every cleaned page against
its raw transcript along the same 8 dimensions the 2026-05-11 manual
spot-check used. Writes per-page verdicts to a new sidecar
`pages_cleaned_qc.jsonl` with the same idempotency/provenance shape as
the cleaner. The manual 5-page spot-check becomes a calibration tool
for the judge rather than the only quality signal.

## Why

The cleanup pass produces ~4,153 cleaned pages per corpus run. Manual
spot-check at 5 pages is enough to make a go/no-go on the *first* run,
but it doesn't scale to:

- Future tranches (every CSV poll surfaces new cards)
- Prompt iterations (any change to `prompt.py` invalidates the
  idempotency cache and re-cleans the affected pages — we need
  cheaper-than-human signal on whether the new prompt is better
  or worse)
- Methodology surface (a published "we hand-checked 5 of 4,153 pages"
  reads weaker than "every page graded by an independent LLM judge,
  with sampled human re-checks for calibration")

The discipline shift is **calibration, not delegation**: human
judgment stays in the loop, but on the right sample. The judge does
the per-page coverage; the operator validates the judge.

## Cost (order of magnitude)

| Item | Sonnet-4.6 judge | Haiku-4.5 judge |
|---|---|---|
| Per page | ~$0.010 | ~$0.0015 |
| Corpus run (4,153 pages) | ~$42 | ~$6 |
| Per future tranche (50 pages) | ~$0.50 | ~$0.08 |

Recommend **Sonnet-4.6** for the judge. Cost differential is real but
judge quality matters more than judge cost — a miscalibrated judge
that misses a hallucination is worse than a $30 difference.

Sampled human re-check (operator) on ~20 pages per corpus run
catches judge drift cheaply.

## The eight checks, operationalized

Each check returns a structured verdict the judge prompt forces into
a JSON shape. Schema:

```json
{
  "card_id": "...",
  "page": 7,
  "judge_model_id": "claude-sonnet-4-6-...",
  "judge_prompt_sha256": "...",
  "raw_sha256": "...",
  "cleaned_sha256": "...",
  "graded_at": "2026-05-12T14:00:00Z",
  "checks": {
    "hallucinated_facts":      {"verdict": "pass", "evidence": "", "severity": "none"},
    "fabricated_redactions":   {"verdict": "pass", "evidence": "", "severity": "none"},
    "length_ratio":            {"verdict": "pass", "ratio": 1.00, "severity": "none"},
    "voice_match":             {"verdict": "pass", "evidence": "", "severity": "none"},
    "page_boundary_fidelity":  {"verdict": "pass", "evidence": "", "severity": "none"},
    "ocr_artifact_handling":   {"verdict": "pass", "evidence": "", "severity": "none"},
    "verbatim_quotability":    {"verdict": "pass", "evidence": "", "severity": "none"},
    "interpretive_cleanups":   {"count": 0, "examples": [], "severity": "none"}
  },
  "aggregate": {
    "verdict": "pass",
    "hard_fail_count": 0,
    "soft_fail_count": 0
  }
}
```

Verdict values: `pass | soft_fail | hard_fail | not_applicable`.
Severity values: `none | low | medium | high | critical`.

`interpretive_cleanups` is the new dimension surfaced by the
2026-05-11 spot-check: the `1.48 → 1.4a` case. Not a fail — but
counted, sampled, and surfaced in methodology aggregate stats.

### Hard-fail definitions (any one = ship-blocker)

- `hallucinated_facts.verdict == "hard_fail"` — judge identified a
  name, date, place, designator, or event in CLEANED that does not
  appear in RAW.
- `fabricated_redactions.verdict == "hard_fail"` — judge identified
  cleaned text in a region where RAW shows `[REDACTED]`, `XXXXX`,
  black-bar markers, or `[ILLEGIBLE]`.
- `voice_match.severity == "critical"` — judge identified
  AI-marketing voice drift severe enough that a journalist quoting
  the cleaned text would be misled about the source's register.

### Soft-fail definitions (count for aggregate, not ship-blocking individually)

- `length_ratio` outside [0.8, 1.5]
- `voice_match.severity` is `low | medium`
- `page_boundary_fidelity.verdict == "soft_fail"` (cleaned text
  references adjacent pages)
- `ocr_artifact_handling.verdict == "soft_fail"` (bracketed editorial
  markers dropped)
- `verbatim_quotability.verdict == "soft_fail"` (judge wouldn't cite
  cleaned as verbatim of raw)

### Soft-fail aggregate threshold

If `aggregate.soft_fail_count >= 3` on a single page → flag for human
review. If `>= 2%` of corpus has `soft_fail_count >= 2` → pause
before publishing the cleaned mirror.

## Integration shape

### New CLI command

```
pursue clean qc run --manifest data/manifests/latest.json [options]
```

Options:
- `--cards <ids>` — restrict to specific cards (same shape as the
  cleaner's `--cards`)
- `--budget-usd <X>` — cost cap, same shape as the cleaner
- `--judge-model <model>` — default `claude-sonnet-4-6-<latest>`
- `--sample-n <N>` — flag every Nth page for sampled human re-check
  (default 200 → ~20 pages per corpus run)
- `--reclean-on-hard-fail` — if set, hard-fail pages get marked for
  reclean in the next `pursue clean run` (passes through cleaner's
  prompt-version-bump invalidation path; off by default — operator
  decides whether to re-clean)
- `--dry-run` — print planned pages and exit without spending tokens

### Idempotency contract

Mirrors the cleaner's idempotency exactly:

```
should_skip(raw_sha256, cleaned_sha256, judge_model_id, judge_prompt_sha256)
```

If all four match a prior row in `pages_cleaned_qc.jsonl`, skip the
judge call. Changing the judge prompt or the judge model invalidates
the cache and re-grades affected pages.

### File layout

```
/mnt/nas/personal/pursue/ocr/<card_id>/
  pages.jsonl              # raw OCR (existing)
  pages_cleaned.jsonl      # LLM-cleaned (existing)
  pages_cleaned_qc.jsonl   # new — judge verdicts
```

One QC row per cleaned row. Skip-row pages get a corresponding QC row
that records `verdict: "not_applicable"` plus the skip reason so the
aggregate stats can distinguish "no QC because nothing to grade" from
"QC found nothing wrong."

### Web/API surface

- `/methodology` gains a paragraph + an aggregate-stats block:
  *"of 4,153 cleaned pages, X graded clean by Sonnet-4.6, Y flagged
  for interpretive cleanups (most common: per-character OCR fixes
  like `1.48` → `1.4a` in context), Z flagged for human re-check.
  All sampled re-checks (N pages) agreed with the judge."*
- `CardReaderView` (when cleaned-mode toggle is on) optionally
  surfaces a small judge-verdict chip near the page header — green
  for `pass`, amber for `soft_fail`, red for `hard_fail`. Click for
  the judge's structured evidence.
- `/api/retrieve` response gains an optional `qc_verdict` field
  per hit when the consumer requests `include=qc`.

## Bring-up phases

1. **Schema + sidecar I/O** (~half day)
   - `src/pursue_index/clean/qc/sidecar.py` (write/load pages_cleaned_qc.jsonl, `should_skip` cache)
   - `src/pursue_index/clean/qc/schema.py` (typed verdict shape)

2. **Judge prompt + LLM call** (~half day)
   - `src/pursue_index/clean/qc/prompt.py` (judge prompt, sha-pinned)
   - `src/pursue_index/clean/qc/judge.py` (Anthropic client call, structured-output parsing, content-filter graceful skip with `qc_skipped` reason — same family as the cleaner's skip schema)

3. **Runner + CLI** (~half day)
   - `src/pursue_index/clean/qc/runner.py` (iterate cleaned-but-not-judged pages, write verdicts, respect budget cap)
   - Wire `pursue clean qc run` in `cli/commands.py`

4. **Pilot grading on the 6 spot-check cards** (~10 min, ~$0.05)
   - Re-run the 5-page manual checklist on the same pages, compare verdicts
   - Calibration: any disagreement between judge and operator gets logged as a soft-prompt-iteration item

5. **Full corpus grading** (~20 min wall, ~$40 Sonnet / ~$6 Haiku)
   - One-shot pass over `pages_cleaned.jsonl` rows for every card
   - Aggregate stats land in a new `data/benchmarks/clean-qc-snapshot.json`

6. **Web/methodology integration** (~half day)
   - `/methodology` aggregate-stats block + reader-mode chip
   - Documentation of the calibration discipline

## Calibration discipline

The judge MUST be calibrated against operator judgment, or it
becomes an opaque oracle that legitimizes errors.

Calibration pass (~30 min operator attention per corpus run):

1. After every full-corpus QC pass, the runner emits a calibration
   sample: every Nth page (default N=200 → ~20 pages) flagged with
   `calibration_sample: true` in its QC row.
2. Operator reviews the 20 sampled pages, marks agreement or
   disagreement with the judge verdict.
3. Disagreements get logged to `data/qc-calibration/<date>.jsonl` and
   surfaced as prompt-iteration candidates.
4. If operator-judge disagreement rate > 10% on the sample, the
   judge prompt needs work before the next corpus run is trusted.

This is the discipline that distinguishes "automated quality review"
from "letting the LLM mark its own homework."

## Editorial bar for the judge prompt

The judge prompt MUST:

- Define each verdict's pass/soft-fail/hard-fail boundary
  concretely, with examples drawn from the 2026-05-11 spot-check
  (the `1.48 → 1.4a` case, the redacted-content preservation, the
  voice-match question).
- Require structured JSON output (using Anthropic's structured-output
  shape) so verdicts are parseable.
- Forbid the judge from offering remediation suggestions — its job
  is verdict only. (Reasoning: judge models that suggest fixes drift
  toward the "improvements" framing, which biases their verdicts.)
- Cite specific raw vs cleaned text spans as evidence for any
  non-`pass` verdict.
- Abstain when uncertain (`not_applicable` for empty/skip pages,
  `verdict: "uncertain"` for pages where the comparison itself is
  ambiguous — judged-rate-uncertain pages are flagged for human
  review).

## Acceptance

- New `pursue clean qc run` CLI command ships
- `pages_cleaned_qc.jsonl` sidecar produced for every cleaned card,
  idempotent on `(raw_sha, cleaned_sha, judge_model, judge_prompt)`
- Full-corpus pilot completes within budget
- Pilot calibration sample (20 pages) shows operator-judge
  agreement >= 90%
- `/methodology` aggregate-stats block lives
- Reader-mode chip surfaces judge verdict per page

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Judge has its own moderation classifier (e.g. fires on the same Adamski-era content as the cleaner) | Medium | Mirror the cleaner's graceful-skip shape: QC rows can carry `qc_skipped: content_filter` and aggregate stats distinguish "graded clean" from "judge declined to grade." |
| Judge sycophancy: judges tend to agree with the model that produced the artifact | Medium | Calibration discipline (20-page operator sample per run); cross-vendor judging as a future enhancement (Sonnet judges Haiku's cleanup, or vice versa). |
| Judge misses hallucinations the cleaner produced because both used Haiku-4.5 | High | Use Sonnet-4.6 for the judge specifically because it's a different (more-capable) tier. Add OpenAI/Gemini judge as a phase-2 cross-vendor enhancement. |
| Aggregate-stats block over-promises calibration coverage | Low | Methodology page is explicit about the sampling rate and the disagreement-resolution process. No claim of perfection. |
| Cost spirals on prompt iteration | Low | Idempotency on `(judge_model, judge_prompt)`; prompt changes are conscious operator decisions. |
| Judge slows the full pipeline | Low | QC pass is post-cleanup, parallelizable per-card, budget-capped. Not on the critical path for site updates. |

## Out of scope

- Real-time / on-demand grading (this is a batch pass)
- Replacing the human spot-check entirely (calibration sample stays)
- Cross-vendor judging (Phase 2 — OpenAI / Gemini as alternative
  judges; not in this scope)
- Re-running the cleanup itself based on judge verdicts (operator
  decision; runner has the optional flag but it's off by default)
- Generating "improved" cleaned text from judge feedback (judge does
  verdicts only; cleanup iteration is a prompt change, not an
  inline correction)

## Open questions for operator

1. **Sonnet-4.6 or Haiku-4.5 for the judge?** ~$30 difference at
   corpus scale; quality difference is real but unmeasured. Recommend
   pilot with Sonnet-4.6, downgrade only if Haiku-4.5 calibration
   sample matches.

2. **Sampling rate for calibration?** Default proposal is every
   200th page (~20 pages per corpus run = ~30 min operator
   attention). Could go finer (every 100th, ~40 pages) or coarser
   (every 500th, ~8 pages). Trade-off is operator attention.

3. **Should hard-fail pages auto-flag for reclean?** The `--reclean-on-hard-fail`
   flag is off by default. Operator could choose to bake it in to
   the full pipeline so a hard-fail always triggers a re-pass. The
   risk is unbounded cost on a chronically-misbehaving page.

4. **Cross-vendor judging timeline?** Adding OpenAI/Gemini judges in
   parallel gives stronger signal but adds dependency surface. Could
   slot before or after the Black Vault thread. Recommend after.

5. **Surfacing the QC verdict on the live site — too transparent
   or just right?** Showing red/amber chips on cleaned pages is
   maximally honest but adds visual complexity. Alternative: surface
   only aggregate stats on `/methodology`, keep per-page verdicts
   internal. Recommend full surfacing — the discipline IS the pitch.

## Notes on this plan's framing

This is **not** a replacement for the manual spot-check. The 5-page
spot-check from 2026-05-11 is the editorial bar; the LLM judge is the
coverage tool. The 20-page calibration sample per corpus run is what
keeps both honest.

Per the *ship-wired-and-validated* discipline: this plan is not
shipped when the code merges. It's shipped when:
1. The judge runs against the full corpus
2. The calibration sample completes with >= 90% operator agreement
3. The methodology page surfaces the aggregate stats
4. The reader-mode chip surfaces judge verdicts per page

Anything less is dark code.
