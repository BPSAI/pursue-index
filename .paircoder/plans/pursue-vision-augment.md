---
id: pursue-vision-augment
type: feature
status: partially-satisfied
created: 2026-05-10
priority: medium
depends_on: []
---

## Outcome (2026-05-22)

Original goal was a second vision-extraction pass to complement the augmented-retrieval integration. Partially satisfied by: (1) Sprint 4j (2026-05-21): engine-matched Sonnet 4.6 OCR for the 70 altered pre-edit cards; (2) Sprint 4m (2026-05-22): Sonnet-only OCR for the 6 tranche-2 PDFs at the cleanup-pass output. Full Phase-2 corpus-wide re-OCR with operator prompts is no longer load-bearing — the existing Surya+LLM pipeline plus targeted Sonnet passes cover the high-value cases. Revisit if a future tranche surfaces a class of pages where the existing pipeline demonstrably underperforms.


# Pursue-vision-augment (Phase 2 vision-extraction pass)

## Summary

Build a second vision-language extraction pass over the PURSUE corpus,
operated by us with our own prompts, model selection, and coverage
targeting. Ships alongside (not replacing) the alex-zhang42 augmented
retrieval integration that landed at v1.0.0. Per-page provenance
distinguishes the two sources; chat, search, and retrieve surfaces
label both clearly.

## Why

The current `/methodology` framing — augmented retrieval as parallel
research integration — is strong. Adding our own vision pass
strengthens it: where two independent vision systems describe the
same image and agree, that's stronger signal; where they diverge,
that's interesting and citable.

The original integration with alex-zhang42 was the right call at
v1.0.0 — already-done, CC0, project-velocity-respecting. Adding our
own as Phase 2 gives us:

- **Control** over prompts, model selection, and inference budget
- **Reproducibility** — we can re-run any time, against any tranche
- **Coverage targeting** — we can prioritize low-OCR-confidence pages,
  image-heavy cards, redaction-boundary pages
- **Strategic independence** — alex-zhang42's release cadence is not
  in our control

This is **not** a replacement for the alex-zhang42 integration. Two
independent passes are strictly better than one, particularly for a
corpus where photographs, sketches, and rubber-stamped redaction marks
are load-bearing content. The provenance-per-page labeling that
distinguishes them is itself a citable-research positioning asset.

## Cost (order of magnitude)

| Item | Haiku-4.5 vision | Sonnet-4.6 vision |
|---|---|---|
| Per page | ~$0.0007 | ~$0.003 |
| Corpus run (4,153 pages) | ~$3 | ~$12.50 |
| Per future tranche (50 pages) | ~$0.04 | ~$0.15 |

Recommend Haiku-4.5 for the bring-up pass. Sonnet-4.6 if Haiku output
quality is insufficient on the spot-check. Cost is not the blocker.

Storage: negligible. Vision descriptions are short text rows in the
existing `pages.jsonl` sidecar shape; no new schema, no new asset
deploys.

## Integration Shape

A new OCR engine is registered alongside Surya + Anthropic-vision-fallback:

```
pursue ocr run --engine vision-augment
pursue ocr run --engine auto    # may route to vision-augment for IMG cards
                                # or low-OCR-confidence pages
```

Per-page output schema in `pages.jsonl`:

```json
{
  "card_id": "...",
  "page": N,
  "engine": "pursue-vision-augment",
  "model_id": "claude-haiku-4-5-20251001",
  "prompt_sha256": "...",
  "output_sha256": "...",
  "generated_at": "...",
  "text": "[[VISION-AUGMENT via pursue-index]] <description>..."
}
```

The inline source marker `[[VISION-AUGMENT via pursue-index]]` is
distinct from the existing alex-zhang42 marker
(`[[IMAGE-DESCRIPTIONS via alex-zhang42/ufo-pursue-open-atlas]]`),
so retrieval consumers can disambiguate at chunk granularity by
matching either marker.

The "structured `engine` field on `/api/retrieve` hits" gap noted in
`/methodology` (planned-but-unshipped) closes with this work: the
retrieve worker exposes `engine` per hit, sourced from the index's
existing engine label.

## Bring-Up Phases

1. **Add engine module** (~1 day): `src/pursue_index/ocr/vision_augment.py`
   implementing the existing engine interface. Reuses the
   Anthropic-vision-fallback infrastructure but with a different
   prompt + provenance flag. Routes via the `engine: "vision-augment"`
   selector and the `--engine auto` heuristic (IMG-type cards always
   route here; low-OCR-confidence pages optionally route here as a
   secondary pass after Surya).

2. **Pilot run on 30 cards** (~30 min, ~$0.05): seeded sample including
   image-heavy cards, faded carbons, redaction-heavy pages. Operator
   spot-checks the descriptions for quality + voice match
   (see editorial bar below). Same pilot-first pattern as the
   LLM-cleaned reading text feature.

3. **Full corpus run** (~1 hour wall-clock, ~$3 Haiku or ~$12 Sonnet):
   once pilot is approved, run across all 4,153 pages. Output writes
   to per-card `pages.jsonl` sidecars.

4. **Embed pass over the new vision rows** (~$0.10): rebuild the
   embedding index so vision-augment chunks are searchable + atlas-
   plottable. Reuses the existing `pursue embed run` pipeline; the
   new chunks land in the same Voyage-3 1024d shape.

5. **Web/API surface updates** (~half day):
   - `/api/retrieve` response gains a structured `engine` field per hit
   - `CardOcrIsland` and `CardReaderView` display the engine label per
     page (small chip near the page header — `surya` / `anthropic-vision`
     / `augmented-vlm-alex-zhang42` / `pursue-vision-augment`)
   - `/methodology` augmented-retrieval section adds a paragraph on
     the second pass and how the two sources are kept distinct
   - Update the inline `[[...]]` marker documentation so consumers
     parsing snippets can match both markers

6. **A/B comparison artifact** (~half day, optional): write a `/finds`
   entry comparing two vision systems' descriptions of the same UAP
   photograph. Strong editorial differentiator and a citable example
   of provenance-aware retrieval in action.

## Editorial Bar for Vision Descriptions

The vision pass output must:

- **Describe what is visually in the image**, not interpret or
  speculate. "Depicts an oblong illuminated object against a dark
  background" is right. "Appears to be a UAP" is wrong.
- **Preserve document context** — these are U.S. government
  UAP-related document images, not standalone photographs. Note
  visible classification banners, document IDs, page numbers, and
  any stamp/redaction marks as part of the description.
- **Use plain descriptive language** — no AI-marketing voice, no
  flowery prose. The same register as the existing `/finds` editorial
  entries.
- **Abstain when uncertain** — "the image appears too degraded to
  describe with confidence" is a legitimate output. Don't hallucinate
  detail.
- **Be cite-friendly** — a journalist quoting the description should
  be able to use it without paraphrasing.
- **Acknowledge the engine** — outputs include the inline marker
  `[[VISION-AUGMENT via pursue-index]]` at the start so consumers
  parsing snippets can route on it.

## Acceptance

- New `pursue-vision-augment` engine ships, CLI-invocable
- Pilot output passes editorial spot-check (no AI slop, factually
  grounded in image content, register matches existing entries)
- Full corpus run completes within budget
- `/api/retrieve` surfaces the per-hit `engine` field (closes the
  planned-but-unshipped methodology claim)
- alex-zhang42 integration remains intact and visible alongside the
  new pass — provenance labels distinguish them at chunk granularity
- `/methodology` documents the second pass with the same honesty bar
  as the first

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Vision descriptions drift into AI-slop voice | Medium | Pilot-first; operator spot-check before full corpus run; explicit editorial bar in the prompt |
| Hallucinated detail in image descriptions | Medium | Prompt emphasizes "describe what is visually present, abstain when uncertain"; pilot reviews catch egregious cases |
| Two-source provenance complexity confuses casual readers | Low | UI displays both labels clearly; `/methodology` covers the rationale; chat citation form treats them as parallel sources |
| Future divergence from alex-zhang42 maintenance pattern | Low | We control our pass; their pass remains as-is; no coupling beyond marker convention |

## Out of Scope

- Replacing or removing the alex-zhang42 integration (explicitly KEPT
  — provenance labels distinguish the two sources at chunk granularity)
- Re-OCR of document text content (existing Surya / Anthropic-vision
  fallback handles text; vision-augment is for image content and
  document-image context)
- Real-time / on-demand vision descriptions (this is a build-time
  enrichment pass; per-tranche delta runs are batch)
- Image-classification taxonomy beyond what naturally falls out of
  the descriptions (no "category: photograph | sketch | stamp" labels)

## Open Questions for Operator

1. Haiku-4.5 vs Sonnet-4.6 for the bring-up pass? Cost difference is
   ~4× but the description quality at Haiku may be plenty for the
   editorial bar. Recommend pilot-first at Haiku, upgrade only if
   spot-check flags quality issues.
2. Coverage strategy: vision pass on **every** page (simpler;
   redundant on text-only pages where Surya already gives a clean
   transcript) vs. **selective** (route only IMG-type cards + pages
   where Surya/Anthropic-vision-fallback signaled low confidence)?
   Selective is more efficient; full-coverage gives a uniform
   second-source for every page.
3. Should the new engine output be visible in `/atlas` as a separate
   color/category, or stay in `/search` and `/card` surfaces only?
   Atlas separation could over-segment the projection; recommend
   keeping atlas as-is (one dot per page, regardless of source) and
   exposing the engine label only on hover/select.
4. Phasing: when does this thread fit best — after Black Vault wraps?
   Before? In parallel? Recommend after Black Vault because Black
   Vault is the higher-impact next major thread, and pursue-vision-
   augment is a quieter enrichment that doesn't block anything.
