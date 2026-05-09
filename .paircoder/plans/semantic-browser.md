---
id: semantic-browser
type: feature
status: backlog
created: 2026-05-09
priority: medium
depends_on: [embed-stage]
---

# 2D semantic browser (`/atlas`)

## Why

A r/DataHoarder commenter asked for "a browseable semantic embeddings
[view], so it'd be possible to see connections on various topics."
alex-zhang42's parallel project ships a 3D atlas at
`https://ufo.gpt2077.com/` — visually striking but not a working
navigation surface. We already have everything we need: 1024-dim
Voyage-3 embeddings for all 4,153 pages in `embeddings.bin`, page
metadata in `pages.json`. We just lack the projection and the view. The
differentiator is *navigability*, not *spectacle*: dots are clickable,
hover shows snippets, search filters live, click jumps into the reader.

## Projection

**UMAP, build-time, seeded.** UMAP preserves topological structure
better than t-SNE for navigation (t-SNE distorts global geometry; UMAP
keeps cluster relationships interpretable). PCA is a fallback if UMAP
takes too long, but at 4,153 × 1024 it runs in under a minute on CPU.

Run at build-time, not in browser: a 5s UMAP on page load is jarring,
and it ties us to ship `umap-js`. Build-time produces a static JSON
shipped as an asset; the browser loads it instantly.

`umap-learn` goes into a `[build-tools]` extra in `pyproject.toml`, not
runtime deps. Pin `random_state=42` so reruns are reproducible — UMAP
is non-deterministic without it and reviewers will notice if the layout
churns between commits.

**2D, not 3D.** 3D is alex's angle. 2D is a working surface; pan and
zoom on a plane is muscle memory, 3D rotation isn't. Mobile especially
benefits.

Output: `web/public/data/atlas-layout.json` ≈ 200 KB, shape
`[{x, y, card_id, page, agency, cluster_id}]`. Lazy-loaded only on
`/atlas`.

## Visualization

**regl-scatterplot** (WebGL via regl). 4,153 dots is trivial in canvas
too, but regl-scatterplot gives free zoom/pan, density-aware dot
sizing, lasso selection, and antialiased rendering — features we'd
otherwise reimplement. Bundle cost ~50 KB gzipped.

- **Color:** by agency using existing palette tokens (DOW / FBI / NASA
  / DOS). A toggle exposes `cluster_id` from k-means k=8 over the
  layout coordinates as an alternate coloring.
- **Hover:** snippet from `pages.json` in a small floating tooltip.
- **Click:** routes to `/card/<id>#page=N`.
- **Search:** input above the canvas. Reuses the MiniSearch index
  already built into `pages.json`. Matches glow; non-matches dim to
  ~15% opacity. No re-layout, just re-color.
- **Lasso (stretch):** drag a region → side panel lists selected
  pages with snippets. Defer if it adds friction.

## Build pipeline

New script: `scripts/build_atlas_layout.py`. Reads `embed_index.json`
and `embeddings.bin`, runs UMAP, k-means for cluster_id, writes
`atlas-layout.json`. Idempotent: SHA-keyed off the embeddings file, no
work if unchanged. Wired into the post-embed step so `ingest_new_tranche.sh`
regenerates layout when new tranches land. Augmented Voyage embeds
(post-PR-#2) flow through automatically.

## Layout / navigation

- **Route:** `/atlas`. Lazy-loaded.
- **Discovery:** homepage hero CTA ("explore by topic →") and a top-nav
  entry after FINDS.
- **Mobile:** keep the canvas, shrink dots, tap-to-show tooltips
  (no hover on touch). If the canvas feels cramped under 400px wide,
  fall back to a cluster-grouped list view of `cluster_id` buckets
  with snippets — same data, list shape.

## Methodology disclosure

Add an *Atlas* section to `/methodology`:
- UMAP is a low-dim approximation; cluster boundaries are not official
  topic groupings.
- The layout depends on `random_state` and would shift if rerun
  unseeded.
- Color-by-cluster is an unsupervised k-means over 2D coordinates, not
  a curated taxonomy.

Underclaim deliberately. The atlas is a *lens*, not a ground truth.

## Risks

- **Overlap in dense regions.** Pages from the same card or near-duplicate
  topics will pile up. Decision: honor it as signal — density *is* the
  message — but allow a "jitter on zoom" toggle for power users.
- **Mobile interaction.** Hover is hard. Tap-to-show + a clear
  "tap a dot" affordance on first load.
- **Reproducibility.** Pin `random_state` and `umap-learn` version in
  pyproject; regenerate-on-tranche.
- **Bundle weight.** regl-scatterplot adds ~50 KB; lazy-load the route
  so non-atlas visitors don't pay.

## Out of scope

- Inter-card edges / graph view (separate project).
- Multi-modal (image+text) embedding.
- Filter chips (agency, date, disclosure status) — could be v2.

## Effort

- `build_atlas_layout.py`: 2–3h
- `/atlas` route + regl-scatterplot integration: 4–6h
- Polish + mobile fallback: 1–2h
- **Total:** 1–2 day spike.

## Recommendation

**LAUNCH.** No upstream decisions are blocked. UMAP, build-time,
regl-scatterplot, `/atlas`, color-by-agency-default — all defaults are
defensible and cheap to revisit. The shape of the work is small enough
that the operator will learn more by shipping than by debating. Ship,
watch where it lands, refine in flight.
