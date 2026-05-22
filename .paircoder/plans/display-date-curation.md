---
id: display-date-curation
type: chore
status: superseded-by-pursue-curate
created: 2026-05-11
priority: medium
depends_on: [curated-finds]
---

## Outcome (2026-05-22)

Operator-attended chore originally scoped here. Now belongs in pursue-curate as one of the per-surface suite specs (e.g., `suites/timeline-display-date.curate.yaml`). The pursue-curate agent provides the side-by-side review UI, durable verdict storage, and rule-pattern codification that this plan envisioned. Timeline display-date curation will land as Sprint 5e or 5f in the curate sprint sequence.


# Display-date curation for /timeline + manifest hygiene

## Summary

Write a curated `display_date` (and optionally `display_date_range`)
per card via an agent-drafted + operator-approved pass — the same
workflow that curated /finds already uses. Unblocks the /timeline
phase of the visual-browse-surface plan and corrects the manifest
`incident_date` discrepancies tracked in Issue #36.

## Why

The current manifest carries `incident_date` for some cards but:

- ~60% of cards have `null` — FBI omnibus files (e.g. 62-HQ-83894
  sections) cover decade-spanning ranges, not points. The CSV's
  point-date field is the wrong shape for them.
- Some cards have demonstrably-wrong dates. D23 (card
  `d8e5687dc870892d`) has `incident_date: 10/31/2023` but the
  MISREP body's Zulu DTGs (`240015:00ZOCT23` /
  `242058:00ZOCT23`) place the sortie on October 24, 2023. The
  in-entry clarifier (`d7258e9`, 2026-05-11) closed the
  user-facing risk but the manifest field is still wrong.
- The /timeline phase of `/gallery` is blocked without a clean
  per-card date.

The right answer for cards lacking a point date isn't "leave null"
or "guess." It's a curated `display_date` field that respects what
the document actually says, plus an evidence citation for journalists
doing diligence.

## Workflow (mirrors curated /finds)

1. **Writer agent** reads the card's PDF metadata + first-page OCR
   + document-body DTGs + agency declassification stamps.
2. **Proposes** `display_date` (or `display_date_range`) with cited
   evidence — a short span from the source identifying the date.
3. **Operator reviews** in a single-pane UI: proposed date,
   evidence span, agency/source context. Keyboard:
   `a` accept / `e` edit / `r` reject / `s` mark as "no defensible
   date" abstention.
4. **Approved entries** land in `data/display_dates.json`, a
   curated mirror that overrides manifest values at deploy time.
5. **Build script** merges display dates into the manifest at
   build time; preserves the original CSV value in a sibling
   `manifest_incident_date_raw` field for audit.

This pattern mirrors curated /finds: agent draws the heavy load;
operator's job is review, not authoring from scratch.

## Schema

Per curated card row:

```json
{
  "card_id": "...",
  "display_date": "2023-10-24",          // YYYY-MM-DD point date
  "display_date_range": ["1947-01", "1947-12"],  // optional, ISO 8601 range
  "display_date_evidence": "MISREP DTG 240015:00ZOCT23, p1",
  "display_date_evidence_card_ref": "d8e5687dc870892d#page-1",
  "display_date_curator": "operator-david | agent-haiku-4-5",
  "display_date_approved_at": "2026-05-12T10:30:00Z",
  "manifest_incident_date_raw": "10/31/2023"   // preserved for audit
}
```

When both `display_date` and `display_date_range` are present,
`display_date` is the canonical point for /timeline plotting; the
range renders as a chip suffix (e.g. "Oct 24, 2023 *(within range
1947-1968)*").

A first-class **abstention** option:

```json
{
  "card_id": "...",
  "display_date": null,
  "display_date_abstention": "FBI omnibus file 62-HQ-83894 Section 3 covers 1947–1968; no defensible single document date",
  "display_date_evidence": "FBI declassification stamp May 24, 2007"
}
```

The /timeline UI surfaces abstained cards in a separate "undated"
bucket — visible, not hidden.

## Bring-up phases

1. **Schema + build-script merge** (S, ~12cx).
   - Write `data/display_dates.json` file structure.
   - Update build pipeline to merge curated dates into
     `latest.json` at deploy time, preserving raw CSV values.

2. **Writer agent** (M, ~25cx).
   - Prompt for date inference with **evidence requirement**;
     refuses to propose without a cited span.
   - Output schema validated against the row shape above.
   - Estimated cost: ~$0.005/card × 161 cards = ~$0.80.

3. **Operator review UI** (M, ~30cx).
   - Single-pane Astro page (local-only or operator-auth-gated).
   - Walks through proposals in queue order.
   - Keyboard shortcuts: `a` accept / `e` edit / `r` reject /
     `s` mark abstention / `→` next.
   - Persists queue state across sessions; resumable.
   - Diff display: proposed date + evidence next to the manifest's
     current value.

4. **Initial pass** (operator time, ~2-4 hours).
   - Writer agent runs over all 161 cards in batch.
   - Operator walks through ~161 proposals at ~30-60 sec/card
     review pace.
   - Approval rate target: 80%+ on first agent draft (sloppier
     agent → more operator edits, slower pass).

5. **Issue #36 close** (XS, ~5cx).
   - Verify D23 has correct curated date.
   - Verify other modern D## entries are correct.
   - Close issue with link to `data/display_dates.json`.

Total: ~75-85cx + ~2-4 hours operator time. Could ship in a
sprint with parallel driver + operator review tracks.

## Editorial bar

These rules are load-bearing — they're what makes the curated dates
trustworthy enough to surface in /timeline:

- **Every `display_date` row carries cited evidence.** No bare
  dates. Evidence must be a short verbatim span from the source.
- **When document body and manifest disagree, document body wins.**
  Same logic that drove the D23 in-entry clarifier on 2026-05-11.
- **"Approximate" dates require evidence framing.** "Circa 1947
  per FBI declassification stamp" is acceptable; "around 1947"
  is not.
- **Year-only entries** (`display_date: 1965`) are acceptable
  when the document body supports only year-level precision.
  Plotted as Jan 1 of that year; rendered as "1965" in chips.
- **Abstentions are first-class.** "No defensible date" is a
  legitimate output that surfaces in /timeline as an "undated"
  bucket — not hidden, not invented.

## Acceptance

- All 161 cards have either a curated `display_date` /
  `display_date_range` OR a documented abstention.
- Issue #36 closes.
- `/timeline` phase of visual-browse-surface is unblocked.
- `pursue scrape run` regenerates `latest.json` with curated
  dates merged in (idempotent).

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Operator review time exceeds budget | Medium | Agent does heavy lift; operator just approves with keyboard shortcuts. Sustainable rate ~30-60 sec/card → 1-2 hours total. |
| Writer agent fabricates evidence | High | Schema requires citation span; review UI surfaces the cited text adjacent to the proposed date. Operator catches in review. Same risk class as curated finds; same mitigation works. |
| Cards genuinely lacking documentary date | Medium | "No defensible date" abstention is first-class; not a workaround. The /timeline UI shows abstained cards in their own bucket. |
| Re-running drift on new tranches | Low | Per-tranche cards run agent + operator pass; not a full re-curation. |
| Display dates diverge from chat citations | Low | Chat sources from the document body, not the manifest; display dates are surface metadata, not RAG context. |

## Open questions for operator

1. **Writer agent model**: Haiku-4.5 or Sonnet-4.6 for date
   inference? Date reasoning is non-trivial (parsing Zulu DTGs,
   resolving year-only contexts, dealing with FBI section
   declassification timelines). Recommend Sonnet-4.6 for the
   bring-up pass at ~4× cost — quality of evidence citation
   matters more than per-card cost. Total spend either way is
   under $5 for the corpus.

2. **Review UI shape**: Astro page on the live site (gated
   behind operator auth) vs. local-only Astro app vs. CLI
   prompt loop? Local-only is the smallest surface and keeps
   the curation flow off the public site. Recommend local
   Astro app launched via `npm run curate:dates`.

3. **Future automation**: Once the clean-quality-review judge
   (`.paircoder/plans/clean-quality-review.md`) is calibrated,
   it can be extended to grade `display_date` proposals
   (verify cited evidence exists in the source, verify the
   date matches the cited evidence). Phase 2 enhancement, not
   in current scope.

4. **Re-curation cadence**: when a new tranche surfaces a card
   that already has a curated date, do we re-run the writer
   agent or trust the prior entry? Recommend: prior entry
   wins, but flag in a "dates-to-review" issue on the tranche
   diff page so operator can re-confirm.
