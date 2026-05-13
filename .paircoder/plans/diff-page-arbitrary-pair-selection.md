---
id: diff-page-arbitrary-pair-selection
type: feature
status: backlog
created: 2026-05-13
priority: medium
depends_on: []
---

# `/diff` page — arbitrary snapshot-pair selection + per-snapshot timeline

## Recommendation

**Add two snapshot selectors (left = older, right = newer) + a
timeline strip showing per-snapshot summary counts.** Keep the current
default landing experience (newest-vs-prior, no UI cost, instant
load) so the most-common question — "what changed in the latest
tranche?" — still answers in zero clicks. The selectors are
opt-in for visitors who want the multi-snapshot view.

## Background

Current behavior (shipped in v1.0.0 alongside the auto-poll workflow):
`DiffIsland` reads `web/public/data/snapshots/index.json`, picks the
two newest entries, and renders the per-card delta (added /
removed / field-changed) between them. The "always compare newest
two" choice was the right MVP at 2 snapshots — minimal UI, fast load,
covers the headline question.

At three snapshots (current state: 596cc188, 0d7e9ba1, 65572b38) the
limitation starts to show. At ten or fifty snapshots — a likely state
within a few months given the 30-minute poll cadence and operator
ingest pace — the inability to compare arbitrary endpoints
undersells the project's preservation guarantee.

## Why this is editorial, not just engineering

The project's distinguishing claim is **preservation of an evolving
public archive** — bytes, manifests, and per-card identities held
across time even when upstream removes, renames, or restores entries.
The diff page is the surface where that claim becomes legible to a
visiting researcher. A diff page that can only answer "what changed in
the latest 30-minute poll" undersells what the system actually
preserves.

Concrete questions the current design can't answer:

| Question | Current `/diff` | All-vs-all selectable |
|---|---|---|
| What changed in the latest tranche? | ✅ default view | ✅ default view |
| What changed between May 8 release and today? | ❌ requires multi-hop walking the snapshots manually | ✅ pick endpoints from dropdowns |
| When did D032 first show duplicate-asset_url cataloging? | ❌ | ✅ binary-search across snapshots |
| What's the full evolution of FBI Section 6 (May 8 → removed → restored)? | ❌ | ✅ visible across pairings + timeline |
| What changed cumulatively over a quarter? | ❌ | ✅ pick first/last snapshots of period |

Each of these is plausibly asked by a researcher or journalist who
arrives at the site to verify a claim about upstream behavior. The
current design forces them to download multiple snapshots and diff
them locally; the proposed design surfaces it in a click.

## Proposed design

### Default landing (preserve current behavior)

Page loads with `newest_snapshot` vs `previous_snapshot` already
selected. Diff renders below within ~200ms (snapshots are small
manifest JSONs, ~3 MB each at current corpus scale; lazy-loaded, only
two fetches on default).

### Selectors

Two `<select>` elements above the diff body:

```
Compare:  [<- older snapshot ->]  →  [<- newer snapshot ->]
          ▼ 596cc188 — 2026-05-08 — 161 cards     ▼ 65572b38 — 2026-05-12 — 158 cards
```

Each `<option>` shows: `{csv_sha[:8]} — {fetched_at_date} — {total_cards} cards`.
Sort options chronologically (oldest at top, newest at bottom).
Default: left = `previous`, right = `newest`. On change, lazy-fetch any
snapshot not already loaded, re-render the diff.

Validation: refuse to render if left and right are the same snapshot.
Refuse if left is newer than right (swap or warn). Soft-validate at
the UI layer; the diff renderer assumes left-older / right-newer.

### Timeline strip

A small horizontal strip above the selectors showing one tick per
snapshot, with summary counts on hover/focus:

```
●—●—●  ←  3 ticks (one per snapshot)
   ↓
   65572b38 (2026-05-12)
   158 cards · 16 renamed · 1 restored · 0 net new
```

Click a tick → set right-side selector to that snapshot, left-side to
the prior one. (Quick-jump to "what happened in this single snapshot
event.")

### Rename-aware rendering

When two snapshots straddle a known rename event (per
`data/card-aliases.json`), the diff should NOT show "card X removed"
+ "card Y added" as separate events. Instead show a single "card X →
card Y (renamed)" entry with the alias method (`byte_collision` /
`operator_manual`) noted. This was a lurking gap in the current
diff output even at the default view.

### State persistence

URL-state via `?from=<sha>&to=<sha>` so a diff view is shareable.
Defaults if absent. Same pattern as `/search?q=...&agency=...`.

## Implementation surface

| File | Change | Effort |
|---|---|---|
| `web/src/components/DiffIsland.tsx` | Add selector state, lazy-fetch logic, URL sync, timeline component | ~2 hours |
| `web/src/components/DiffTimeline.tsx` (new) | Small timeline strip with hover summary | ~45 min |
| `web/src/lib/diff-renderer.ts` | Rename-aware grouping (consume `data/card-aliases.json`) | ~1 hour |
| `tests/unit/test_diff_island.test.ts` (new — Vitest) | Selector behavior, URL sync, alias-aware grouping | ~1 hour |
| `web/src/pages/diff.astro` | Pass aliases prop into DiffIsland | ~10 min |

Total: ~5 hours TDD'd.

## What to defer

- **Cumulative across-many-snapshots aggregation.** "Show all changes
  to D032 across every snapshot" is a useful researcher view but
  bigger UI work; defer to a separate plan if the demand surfaces.
- **Atlas-style rename graph.** Visualizing the rename chain as a
  graph (node = card_id, edge = alias) is interesting but adds
  significant rendering complexity; not worth it at 17 aliases. Re-
  evaluate at 100+.
- **Snapshot-vs-snapshot for the asset bytes themselves** (not just
  manifest metadata). The byte-archive registry already records
  byte_sha256 per asset; a "did the bytes change between snapshots"
  view would query the registry rather than the snapshots. Different
  data source, different plan.

## Risks

- **Payload growth.** At ~3 MB per snapshot manifest, loading 10
  snapshots client-side = 30 MB. Mitigation: lazy-load (only fetch on
  selector change, cache in memory once loaded). Today's three
  snapshots = 9 MB worst case if user explores all pairings.
- **URL-state collision.** `/diff?from=&to=` is greenfield; no
  existing URL params on this page. Low risk.
- **Browser-side perf at large card counts.** The diff renderer walks
  the cards array twice (added / removed) and joins on card_id;
  O(n+m). At 158 vs 158 = trivial. Stays fine until N > ~5000.
- **Editorial complexity around renames.** A snapshot-pair that
  straddles a rename without the alias being established yet (i.e.,
  pre-approval) shows the rename as add+remove. Once `pursue ingest
  approve` materializes the alias, the diff updates. Worth a tooltip
  explaining.

## Editorial framing for visitors

A short header on `/diff`:

> Every snapshot of the upstream PURSUE catalog is preserved here.
> Use the selectors below to compare any two — see what was added,
> removed, renamed, or quietly modified between them. The default
> view shows the most recent change.

## When to ship

Not urgent at 3 snapshots. The right time is **before the snapshot
count gets large enough that researchers actively need the multi-pair
view** — say 8-10 snapshots, which at 30-min poll cadence + ~weekly
upstream changes is roughly a 2-3 month horizon. Pairs naturally
with the release-pipeline-gate work since both touch deploy-side
coherence and the same set of files.

## Out of scope

- Editorial copy on the rename UX (operator-curated)
- Atlas integration (would be a separate visualization)
- Diff-as-RSS or similar push-notification surface
