# Sprint 4h plan — OCR text-diff for the 79 altered cards

> **Status (2026-05-22)**: shipped-then-paused. Sprint 4h shipped
> 2026-05-20 (commit a7b3dae). The 79-card /altered/ surface went live
> with OCR text-diff per card. Subsequently taken offline 2026-05-21
> (Sprint 4k-recal) when operator spot-checks showed the algorithmic
> content_changed classification produced false positives on OCR-rescan
> noise. Operator review now happens via pursue-curate (separate repo);
> verdicts will determine which cards return to the public surface. The
> OCR-diff infrastructure itself remains in place; only the publication
> of unverified verdicts was withdrawn.

Captured 2026-05-20 after Sprint 4g merged. Converts the May-14
redaction event from a true-but-unsurfaced integrity claim into a
visible, citable "look exactly what they removed" surface.

## Motivation

Sprint 4g exposed the 79 silent-overlay byte events at the byte
layer: /altered table, per-card banner, /archive/<sha>.<ext> route.
That's necessary but not sufficient — visitors still have to
download both PDFs and diff in their own viewer.

This sprint adds the OCR text-diff surface: for every affected
card, a deep-dive page at /altered/<card_id>/ showing the pre-edit
OCR text vs post-edit OCR text with redactions/additions
highlighted inline. Linkable; reproducible.

## Operator decisions needed before kick-off

1. **Engine.** Sonnet 4.6 single-pass (matches site contract,
   $20-60 for all 79 cards) — recommended. Or gpt-5.4 fallback
   (3× cheaper, 1pp higher CER).
2. **Scope.** All 79 / subset (>30% size delta, ~30 cards) /
   curated subset (~5-10 cards).
3. **Budget.** Confirm $0-60 envelope; budget gate at
   ~$15 max-per-card via Anthropic max-tokens cap.
4. **Attendance window.** Per feedback_no_autospend the OCR
   re-run needs operator-attended dispatch + monitoring. Estimate
   15-30 min of attention; remainder of sprint is unattended.

## Phase 1 — `scripts/reocr_altered.py`

Pipeline to OCR the 79 post-edit byte versions using the existing
Sonnet 4.6 single-pass contract from `pursue ocr run`.

- Input: byte-history.json (current entry for each multi-sha card)
- Pulls the bytes from R2 (`archive/<byte_sha256>.<ext>`)
- Routes through the OCR pipeline (same engine + prompt as the
  site's canonical OCR pass; per state.md Sonnet 4.6 single-pass)
- Output: `data/altered-ocr/<card_id>/<byte_sha>/pages.jsonl`
- Idempotent + resumable: skip cards already OCR'd; on retry,
  resume from page N
- Progress + cost reporting throughout
- Tests: orchestration only (no API in CI); mock the engine,
  verify resume / skip / cost-cap behavior

Sub-decision: handle non-PDF assets? 9 of the 79 are .mp4 (DVIDS
videos preserved). OCR doesn't apply to video bytes. Skip those.
Surface as a "no text-diff applicable; bytes diff only" note on
the card page. ~70 cards are OCR-targets, ~9 are byte-only.

## Phase 2 — `scripts/build_altered_diffs.py`

Pure-Python sentence-aware text-diff. Reads:

- Pre-edit OCR: existing `data/pages-cleaned.json` (May-12 build)
- Post-edit OCR: `data/altered-ocr/<card_id>/<byte_sha>/pages.jsonl`

Produces `web/src/data/altered-diffs.json` keyed:

```
{
  "<card_id>": {
    "pages": [
      {
        "page_no": 1,
        "segments": [
          { "kind": "equal", "text": "..." },
          { "kind": "removed", "text": "..." },
          { "kind": "added", "text": "..." },
          { "kind": "modified", "before": "...", "after": "..." }
        ]
      }
    ],
    "summary": {
      "removed_words": 247,
      "added_words": 3,
      "modified_pages": [3, 4, 5, 7],
      "first_change_page": 3
    }
  }
}
```

Diff algorithm: sentence-level via difflib + custom sentence
boundary detection (PDF OCR has reliable sentence boundaries for
most documents; bullet lists / tables degrade gracefully to
paragraph-level).

Determinism + idempotency tests. Diff snapshot tests against
synthetic before/after pairs covering: pure deletion, pure
addition, in-place modification, redaction-block replacement (the
canonical "BLOCK SCRATCHED OUT" pattern in declassified docs).

## Phase 3 — `web/src/pages/altered/[card_id].astro`

Per-card deep-dive page. Side-by-side desktop / stacked mobile.

- Top: summary stats ("247 words removed, 3 added across pages
  3-7"). Date detected. Both byte_sha short refs + size delta.
- Side-by-side viewer: page-by-page, scrolled in sync. Red
  strikethrough for removed text, green underline for added,
  amber italic for modified-in-place.
- Cross-link to /archive/<sha>.<ext> for both byte versions + the
  card detail page.
- JSON-LD: schema.org/Dataset for crawler / LLM discoverability.

Mobile: stacked diff (before block, then after block, then equal
text condensed). Test plan covers both viewport widths.

Performance: lazy-load pages 2+ on scroll (page 1 inline) so big
documents don't blow up first-paint. Same pattern as the existing
card-detail OCR section.

## Phase 4 — discoverability

- /altered table: new column "View text diff →" linking to
  /altered/<card_id>/ for OCR'd cards; "(video, bytes only)" for
  the .mp4 9.
- card-detail banner: new line "Exact text changes: see the
  side-by-side diff at /altered/<card_id>/."
- sitemap.xml: add /altered/<card_id>/ paths
- llms.txt: include /altered/ as a discoverability entry

## Phase 5 — gate + ship

- bpsai-pair arch check on every touched file
- Full python + web + worker test suites
- Bundle commit per feedback_bundled_commits
- Push + open PR with @codex review + dispatch
  nayru/laverna/vaivora triad
- Update state.md

## Time estimate

- Phase 1: 2h impl + attended OCR run (15-30 min)
- Phase 2: 2h
- Phase 3: 2h
- Phase 4: 1h
- Phase 5: 1-2h
- **Total: 8-10h across 2-3 sessions**

## Cost estimate

Per state.md operated VLM answer: Sonnet 4.6 single-pass at
~$0.013/page.

- All 79 cards (skip 9 video): 70 cards × ~50 pages avg = ~3,500
  pages × $0.013 = **~$45** ($20-60 range)
- Subset 30%+ shrink (≈25 cards × ~50 pages): **~$15**
- Curated 5-10 cards: **~$3-8**

Budget envelope per state.md Sprint 6.2: $86 headroom available.

## Related backlog (not in scope, but flagged)

- vaivora P1.1 from Sprint 4g (Disallow /archive/ for AI_ALLOW)
  — operator left as-is; revisit if AI-scraper traffic to
  /archive/ becomes material.
- nayru L1 polish items from Sprint 4g — defer.
- Pre-existing apollo-17.png test failure on main — file
  separately as `chore(finds): rebuild apollo-17.png`.
- /removed copy update reflecting two entries' content was
  re-published under new card_ids — editorial pass.

## How to start next session

1. Read `.paircoder/context/state.md` for current status.
2. Read this file (`.paircoder/plans/altered-ocr-diff.md`) for
   the implementation plan.
3. Ask operator the 4 decisions above (engine, scope, budget,
   attendance window).
4. Start with Phase 1 TDD per CLAUDE.md.
