---
id: visual-browse-surface
type: feature
status: backlog
created: 2026-05-10
priority: medium
depends_on: []
---

# Visual-first browse surface (`/gallery`, `/timeline`, `/browse`)

## Recommendation

**SHIP `/gallery` FIRST. DEFER `/timeline`. RENAME nothing.**
The corpus already carries the fields a visual surface needs
(`asset_type`, `modal_image_url`, `dvids_video_id`, `incident_date`,
`incident_location`, `agency`, `redacted`); the gap is purely a
presentation layer. A single dense image+video grid at `/gallery`
gives the casual visitor the "see content immediately" hook the
current text-first surface is missing, without rewriting nav or
diluting the citable-research positioning. `/timeline` is the
attractive second move but has real data-quality blockers
(`incident_date` is `null` on most cards in the current manifest);
ship it after a curation pass, not on first principles. `/browse`
as a separate route is unnecessary — INDEX already is the browse
surface; what it needs is a facet rail, not a sibling route.

## The casual visitor / researcher split

Two distinct readers land on a document-archive site and they do
not want the same thing:

| Reader | Wants | Bounces off |
|---|---|---|
| Casual visitor (Reddit, HN, press) | One scroll-frame of "what's in here," recognizable imagery, a few clickable rabbit holes | A blank search box; a 116-row table; the word "manifest" |
| Researcher | A specific document by date / agency / location; the page where a name appears; a stable citation URL | A pretty grid that doesn't let them filter; modal lightboxes that swallow the URL; "infinite scroll" with no permalinks |

Every pattern below is judged on **which of these two it serves
and which it costs.** The dangerous patterns are the ones that
serve the casual visitor by making the researcher's job harder
(modal-only views, infinite scroll, lightbox-trapped images with
no card link).

## What we already have to build on

| Asset | Where | Useful for |
|---|---|---|
| `modal_image_url` (14 cards) | manifest | Image grid tile, hero thumbnail |
| `dvids_video_id` (~30 cards) | manifest | Video gallery (DVIDS embed URL is deterministic) |
| `asset_type` (`PDF`/`IMG`/`VID`) | manifest | Tab filter on a single grid |
| `incident_date`, `incident_location`, `agency` | manifest | Facet rail, map pin, timeline axis (when populated) |
| `redacted` | manifest | Visual badge ("scanline" treatment) |
| PDF first-page rendering | not yet computed | Would unlock a true gallery view of the 116 PDFs |
| Voyage-3 embeddings | `embeddings.bin` | "Visually similar" rail; secondary |
| `card_id#page-N` deep links | already in reader | Citable target for every grid tile |

The single biggest unlock for any visual surface is **first-page
PDF thumbnails**. Without them, "gallery" means 14 images + 30
video posters against a corpus of 160 items — a thin grid. With
them, every card becomes a tile, and the grid is dense from row
one. This belongs as a sibling task (see below) before `/gallery`
ships in its full form, or `/gallery` ships in two phases:
images+video first, then PDF-thumbnail backfill.

## UX patterns considered

### 1. Dense gallery grid (images + video posters)

What it does: one scrollable surface, tile-per-asset, tile shows
thumbnail + agency stamp + date + redaction badge. Tap → card
page (NOT a lightbox). Filter tabs across the top: `ALL / IMAGES /
VIDEOS / DOCUMENTS`. Optional density toggle (small/large tiles).

| | |
|---|---|
| Casual visitor | The headline win. Reduces "what is this" to one scroll. |
| Researcher | Acceptable if every tile has a stable URL and tile→card is a real navigation, not a modal that hijacks the URL. |
| Complexity | **S** (images+video only) → **M** (with PDF thumbnails) |
| Existing assets | `modal_image_url`, `dvids_video_id`, `asset_type`, `agency`, `incident_date`, `redacted` — every field we need is already in the manifest |
| Risks | Bare grid of 14 images reads thin; PDF thumbnail rendering is its own project (Playwright + pdf.js, ~30 MB of WebP assets) |

This is the recommended first ship.

### 2. Faceted-folder navigation (hierarchical tree)

What it does: left rail with `AGENCY → YEAR → LOCATION` drill-down,
right pane shows matching cards. The pattern you see in archival
catalogs and federal reading rooms.

| | |
|---|---|
| Casual visitor | Bounces. Tree-navigation has a learning curve and casual visitors won't invest. |
| Researcher | Genuinely useful — closest pattern to an archival finding aid. |
| Complexity | **M** — facet counts must be precomputed; tree state in URL hash for shareability |
| Existing assets | `agency`, `incident_date` (when present), `incident_location` (when present), `redacted` |
| Risks | Anti-pattern when a facet has only 2–3 cards: the tree feels empty. Our `agency` distribution is small (~6 values); not enough breadth for a tree-rail to feel rich. |

**Skip as a standalone route.** The same data goes further as a
horizontal facet rail on INDEX (see Pattern 7).

### 3. Timeline scroll (chronological axis)

What it does: a horizontal or vertical time axis (1947→2025);
events plotted at their `incident_date`; click → card. Era
backdrops (Cold War, Project Blue Book, post-2017 ODNI cycle)
give context.

| | |
|---|---|
| Casual visitor | High emotional payoff — the timeline IS the story for a UFO corpus. |
| Researcher | Useful for cross-referencing era to source agency. |
| Complexity | **M** standalone, **L** if we want era annotations researched and written |
| Existing assets | `incident_date`, `agency`, `release_date` — but **`incident_date` is `null` on the majority of current cards** (FBI 62-HQ-83894 sections, omnibus files, etc. — they cover ranges, not points) |
| Risks | The blocker. We don't have a clean per-card date for most of the corpus. Synthesizing one is editorial work, not engineering. |

**Defer until a curation pass writes a `display_date` (or
`display_date_range`) field for cards that lack a point-event
date.** Building the timeline against the current manifest yields
a sparse axis that misrepresents what's in the corpus.

### 4. Flipbook / page-turn viewer

What it does: animated page-flip between PDF pages, often with
sound cues, in a fullscreen overlay.

| | |
|---|---|
| Casual visitor | Brief novelty. Hard to skim. |
| Researcher | Actively harmful — slower than scroll, no in-page text selection, no `?page=N` deep link without custom routing. |
| Complexity | **M** (rendering) / **L** (with deep linking and accessibility) |
| Existing assets | None directly; needs pre-rendered page images |
| Risks | This is the "gimmick" pattern — looks impressive in a demo, fights every research workflow. |

**Editorial bar: we don't do this.** The PDF viewer + reader-mode
pair is already the canonical read surface; flipbook animation is
presentation cost for no research value. Document this as an
explicit "we considered and rejected" decision so future
contributors don't re-propose it.

### 5. Modal image lightbox

What it does: tap a thumbnail → fullscreen modal with arrow keys to
paginate adjacent items; URL stays on the grid.

| | |
|---|---|
| Casual visitor | Familiar; expected; low-friction. |
| Researcher | Catastrophic when it replaces card navigation — breaks citation. |
| Complexity | **S** |
| Existing assets | Same as gallery grid |
| Risks | Easy to ship wrong. The lightbox MUST be a peek (tap-to-zoom, escape closes), not the primary destination. Every tile must have a separate "→ card" affordance that updates the URL to `/card/[id]`. |

**Adopt as a peek-only secondary action**, not the primary tile
behaviour. Default tile tap goes to the card page; a small zoom
icon opens the lightbox. The lightbox itself has no "next/prev" —
that would re-introduce the URL-trap problem.

### 6. Video-only gallery

What it does: split out the ~30 DVIDS videos into their own
surface — larger posters, hover-to-preview, transcript snippets.

| | |
|---|---|
| Casual visitor | Highest payoff per tile (video is the most shareable artifact). |
| Researcher | Modest — videos pair with PDFs already, paired view on the card page is the researcher's path. |
| Complexity | **S** as a filter tab inside `/gallery`; **M** as a standalone `/videos` route |
| Existing assets | `dvids_video_id`, `video_title`, `video_pairing`, `pdf_pairing` |
| Risks | DVIDS embed reliability — third-party iframe, occasional downtime; need a fallback poster |

**Ship as a tab inside `/gallery`, not as a sibling route.** ~30
items is below the density threshold for its own route; as a tab
filter the grid stays dense regardless of which type the visitor
chose.

### 7. Search-as-you-scroll facet rail on INDEX

What it does: INDEX gets a left or top facet rail (agency,
year-bucket, asset type, redaction state). Filtering is instant
client-side; URL reflects the active facets so a shared link
reproduces the view.

| | |
|---|---|
| Casual visitor | Doesn't open the rail; the default INDEX view stays scannable. |
| Researcher | Replaces the need for `/browse` entirely. Same data Pattern 2 wanted, in the surface they're already on. |
| Complexity | **M** — facet counts, URL-state encoding, mobile collapse |
| Existing assets | All manifest fields; SearchFilterRail.tsx already exists for `/search` and is the obvious model to extract from |
| Risks | Over-faceting reads like a database admin tool; keep the rail to 4–5 facets max |

**This is the answer to "/browse" without adding a route.** Reuse
the existing search filter component, render it on INDEX, mirror
the URL pattern. The cost is one component refactor and a query-
string contract; the reward is a coherent browse story on the page
casual visitors land on by default.

### 8. Map-first browse (already shipped at `/atlas`)

What it does: `incident_location` plotted on a map; click → card.
Already exists.

| | |
|---|---|
| Status | Shipped. Mention only for completeness. |
| Gap | Atlas and the proposed gallery should cross-link: gallery tiles with a location show a small "→ atlas" affordance; atlas pins for image/video cards show a thumbnail preview. Free wins, no new routes. |

## Phased build plan

### Phase 1 — `/gallery` (images + video), facet rail on INDEX

Two parallel tasks, no PDF-thumbnail dependency. Ship together as
"PURSUE://INDEX gets a browse surface."

- **T?.1 `/gallery` route, images + video tiles only** (M, ~30cx).
  Dense grid, three filter tabs (`ALL / IMAGES / VIDEOS`), tile
  shows agency stamp + date (when known) + redaction badge.
  Default tap → card page; secondary zoom icon → lightbox peek.
  ~44 tiles in the initial view (14 images + ~30 video posters)
  is enough density to read as a gallery, not a placeholder.
- **T?.2 Facet rail on INDEX** (M, ~35cx). Extract
  `SearchFilterRail` into a shared component; render on INDEX;
  encode facet state in URL. Facets: agency, year-bucket
  (release year, since `incident_date` is patchy), asset type,
  redacted. **Do not add a `/browse` route** — INDEX is the
  browse route.
- **T?.3 Nav update** (XS, ~10cx). Add `GALLERY` between FINDS
  and ATLAS in `Base.astro`. Keep the lockup tight; if nav wraps
  uncomfortably on mid-size viewports, drop METHODOLOGY into a
  hamburger before dropping GALLERY.
- **T?.4 Atlas ↔ Gallery cross-links** (S, ~15cx). Tiles with a
  location grow a small "→ atlas" affordance; atlas pins for
  IMG/VID cards grow a thumbnail preview.

Total Phase 1: ~90cx. Single sprint.

### Phase 2 — PDF thumbnails (dense gallery)

- **T?.5 Page-1 thumbnail pipeline** (M, ~40cx). New `pursue
  thumb run` stage: render page 1 of each PDF to WebP at two
  sizes (240×310 and 480×620, ~2× DPR). Idempotency keyed on
  PDF content hash. Outputs land in `web/public/data/thumbs/`
  (~30 MB total at WebP quality 80 across 116 files). Adds 116
  tiles to the gallery. **Asset-budget concern resolved
  2026-05-11**: Cloudflare Workers Static Assets ceiling is
  25 MiB *per file* (not per deployment) and 20,000 files
  total — our thumbnail set is ~150 KB/file across 116 files,
  trivial against both limits. No vendor switch needed.
- **T?.6 Document tab in `/gallery`** (S, ~15cx). Adds the
  `DOCUMENTS` filter tab; tile shows thumbnail + redaction badge
  with the existing scanline treatment.

Total Phase 2: ~55cx. Half-sprint, gated on Phase 1 shipping.

### Phase 3 — `/timeline` (after data curation)

Blocked on a curation pass that writes `display_date` /
`display_date_range` for cards lacking a point `incident_date`.
Not engineering work, editorial work. Estimate this as a separate
plan once the editorial criteria are written.

- **T?.7 `display_date` schema + curation pass** (separate plan).
- **T?.8 `/timeline` route** (M, ~35cx — gated on T?.7).

### Explicitly out of scope

- Flipbook / page-turn viewer (editorial bar — gimmick risk).
- `/browse` as a sibling route (folded into INDEX facet rail).
- `/videos` as a sibling route (folded into gallery tab).
- Hover-to-play video previews (autoplay + sound is hostile to
  the casual scroll; static poster is fine).
- "Visually similar" recommendations from embeddings — interesting
  but it's a research-mode feature, doesn't earn its complexity
  on a casual-visitor surface.

## Editorial bar (load-bearing)

These are the rules a future contributor needs to know before
they propose a visual feature:

- **Every visual tile resolves to a citable URL.** No
  modal-as-destination. The lightbox is a peek; the card is the
  destination. If a feature breaks this, it's the wrong feature.
- **Researcher workflows win ties.** When casual-visitor polish
  conflicts with citation discipline, citation wins. We are not
  a Pinterest board; we are a primary-source archive that happens
  to also be browsable.
- **No animation that costs a research workflow.** Page-flip
  animations, parallax scrolls, and "magazine-style" hero
  treatments are presentation cost; they don't pay for themselves
  on this corpus.
- **Density beats decoration.** A dense, dry grid that fits 30
  cards above the fold reads as "this site has stuff" faster than
  a magazine layout with 6 hero tiles. Match the terminal aesthetic
  — small, scannable, monospaced labels — not a moodboard.
- **Faceting is research-grade or it's not there.** A facet that
  doesn't have a stable URL representation is a toy. Either it
  encodes to query string and reproduces the view, or it doesn't
  exist.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Phase 1 gallery reads thin without PDF thumbnails | Medium | Lead with `IMAGES + VIDEOS` tabs default; keep the `DOCUMENTS` tab disabled with a "coming in v2" tooltip until Phase 2 lands |
| DVIDS embed iframe is third-party and can break | Low | Always render a static poster fallback; embed only on tile expand |
| Adding GALLERY to nav crowds the lockup on tablet viewports | Low | Demote a low-traffic nav item (METHODOLOGY → about subpage) before launch |
| Facet rail balloons into a database UI | Medium | Cap at 4–5 facets; copy the existing `/search` rail's restraint; don't add a facet just because the field exists |
| Page-1 PDF thumbnail render misrepresents a card (e.g. blank cover page) | Medium | Spot-check after first batch; allow a `cover_page: N` manifest override for the ~10 cards where page 1 is uninformative |
| `incident_date` curation becomes a forever-task | Medium | Phase 3 is gated on a written editorial criteria doc, not on field completeness; ship `/timeline` with the cards that have point dates and a note about the rest |

## Open questions for operator

1. **Nav slot:** if GALLERY lands, which existing item gets demoted
   to a sub-link? Current nav has 10 items + GH + preview pill;
   adding an 11th is the line. Candidates: METHODOLOGY (folded
   into ABOUT), CITE (folded into footer only), DIFF (folded into
   methodology).
2. **PDF thumbnail asset budget — RESOLVED 2026-05-11.** The
   historic "25 MB total per deployment" note was incorrect:
   Cloudflare Workers Static Assets actually allows 25 MiB
   *per file* and up to 20,000 files per deployment (Free tier;
   100,000 on Paid). Our ~30 MB thumbnail set across 116 files
   averages ~150 KB/file — well under both limits. Workers
   Static Assets serves them edge-cached at $0 incremental cost.
   No vendor switch needed; PDFs stay on R2 (their size class
   warrants it), thumbnails ship with the static deployment.
   Storage-research details in the 2026-05-11 agent transcript;
   the same research found CF beats S3/CloudFront, Azure Blob,
   Backblaze B2, and GitHub Pages at our scale (and infra cost
   is rounding error in any case).
3. **`display_date` curation owner:** is this a reasoning-agent
   pass with human review (like curated finds), or a one-shot
   manual pass? Affects Phase 3 timeline by ~2 weeks.
4. **Atlas integration depth:** "→ atlas" link only, or full
   inline mini-map on the gallery tile for cards with a known
   location? Inline mini-map is ~3× the implementation cost.
