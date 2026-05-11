---
id: incidents-map-clustering
type: feature
status: backlog
created: 2026-05-11
priority: medium
depends_on: []
---

# Incidents map — geographic density clustering against known features

## Summary

Build a new geographic browse surface (working name `/map`,
distinct from the existing `/atlas` UMAP semantic browser) that
surfaces incident-location patterns through density-aware overlays
against known geographic features: AFB proximity, test ranges,
dark-sky preserves, sparse-population concentration, era
stratification, and co-occurrence views. Pre-computed offline,
rendered as toggleable overlays.

## Why

Every UFO archive shows pins on a map. Few do density-aware
overlay analysis against known geographic features. This is the
operator's pattern-discovery instinct (from the visual-browse-
surface Q4 discussion on 2026-05-11): "the more interesting thing
would be to cluster incident locations that might bring up a
pattern that wasn't observable before doing so."

That instinct is right and underexplored:

- **Research differentiator** — strengthens the citable-research
  positioning beyond "we host the documents." We surface
  geographic structure no other archive does.
- **Pattern-discovery moment for casual visitors** — "I didn't
  realize there was a 1947-1953 cluster around Wright-Patterson"
  is the kind of revelation that gets shared.
- **Hypothesis-generating, not claim-making.** The surface
  doesn't say "this proves X." It says "here's the distribution
  against known features — draw your own conclusions." Matches
  the abstention discipline of the existing chat.

Examples that would surface in initial overlays:

- 1947-1953 cluster near Roswell + Edwards + Wright-Patterson
  (well-known, but visually distinct from later eras).
- 2010-2024 cluster near Nellis Range + restricted airspace
  corridors.
- Sparse-population concentration in Pacific Northwest /
  northern interior — possibly a less-frequented-airspace
  artifact worth surfacing alongside the dataset's other
  caveats.
- Co-occurrence: "Cold War carbon era" looks geographically
  distinct from "post-2017 ODNI cycle" when era-sliced.

## Naming

The existing `/atlas` is the UMAP semantic browser (4,119 dots in
abstract similarity space, not on a globe). The new surface is
geographic — pins on an actual map. Working name `/map` avoids
the naming collision. Alternatives considered:

- `/atlas` — taken, different purpose
- `/globe` — slightly aspirational for a primarily-US corpus
- `/incidents-map` — descriptive but long
- `/geography` — generic
- `/locations` — flat, accurate, fine

Recommend `/map` for the route, "Incidents Map" for the nav
label. Final naming a Phase 1 decision.

## Geographic feature layers

| Layer | Source | Why |
|---|---|---|
| US AFB locations | DoD installation registry (public) + Wikipedia | Wright-Pat, Edwards, Nellis, Groom Lake, Hill, Travis — the well-known clusters |
| Restricted/test ranges | Natural Earth + FAA airspace data (public) | R-2508, R-4806W, Pacific test corridors |
| Dark-sky preserves | International Dark-Sky Association (IDA) list | "Visible UAP needs dark sky" hypothesis test |
| Population density | NASA SEDAC GPW or WorldPop (public) | Sparse-area concentration; less-frequented-airspace correlation |
| Naval exercise corridors | Public NOTAMs archive | Maritime UAP correlation |
| Government science installations | DOE, DOD R&D facility list | Los Alamos, ORNL, Sandia — Cold War era correlation |

All layers ship as pre-rendered static GeoJSON in `data/geo/`.
No live API dependencies — the map stays fully client-side after
initial asset load.

## Overlay types

1. **Heatmap density** — kernel density estimation of pin
   locations, rendered as a semi-transparent gradient over the
   base map. Toggle on/off.

2. **Feature-proximity histogram** — for a selected feature class
   (e.g. "AFB"), show distance-from-nearest-feature distribution
   as a sidebar chart. Click a histogram bin → highlights matching
   pins on the map.

3. **Era stratification** — replay control cycles through era
   slices (1947-1960, 1961-1980, 1981-2000, 2001-2017, 2018-
   present). Each slice shows that era's pins only, plus the era's
   density heatmap. Era boundaries are a curation discussion (see
   Open Questions).

4. **Co-occurrence view** — select two layers (e.g. era × feature);
   highlight cells with both. Pattern-discovery surface.

5. **Single-card mode** — click a pin → opens the card detail
   page. Standard archive navigation; not a modal.

## Bring-up phases

### Phase 1 — Static map + pin layer + AFB overlay (foundational)

- **T?.1 Feature-layer ingestion CLI** (M, ~25cx). `pursue geo
  features fetch`: pulls + caches GeoJSON sources; commits to
  `data/geo/`. Idempotent on source-URL SHA.
- **T?.2 `/map` route + basic pin rendering** (M, ~35cx). New
  Astro page renders pins from manifest `incident_location` (when
  present) via MapLibre + OSM tiles. No overlays yet.
- **T?.3 AFB-proximity overlay** (S, ~20cx). First overlay layer
  toggleable above the base map; renders the DoD AFB layer as
  bright markers + halo.
- **T?.4 Nav integration** (XS, ~10cx). Add "Incidents Map" to nav
  (see visual-browse-surface plan's nav-slot discussion).

Total Phase 1: ~90cx. Single sprint.

### Phase 2 — Density heatmap + remaining layers

- **T?.5 Kernel density pre-computation** (M, ~30cx). `pursue geo
  cluster run` produces clustering output per overlay; idempotent
  on manifest hash + feature-layer hash.
- **T?.6 Remaining feature layers** (M, ~30cx). Test ranges,
  dark-sky preserves, population density, naval corridors, govt
  science sites. Each as a toggleable overlay.
- **T?.7 Era stratification UI** (M, ~25cx). Replay control,
  era-slice rendering. Requires `display_date` curation
  (see `.paircoder/plans/display-date-curation.md`).

Total Phase 2: ~85cx. Single sprint, blocked on display-date
curation for era slicing.

### Phase 3 — Co-occurrence view + editorial layer

- **T?.8 Co-occurrence selector** (M, ~30cx).
- **T?.9 `/map/patterns.md` editorial** (S, ~15cx). Documents
  data sources, abstention bar, hand-curated highlight cards.
- **T?.10 Hand-curated /finds entry** (operator time). One or
  two /finds entries documenting the most striking patterns —
  with explicit "this correlates; this is not causal" framing.

Total Phase 3: ~45cx + operator editorial. Half sprint.

## Editorial bar

These are load-bearing — they're what keeps the surface
honest:

- **No causation claims.** Surface clusters; don't explain
  them. "There is a 1947-1953 cluster near Wright-Patterson"
  is fine. "AFBs are correlated with UAP sightings" is not —
  it conflates "people-near-AFBs report UAP" with "UAP
  appear near AFBs."
- **Cite every data source.** DoD installation registry, IDA
  dark-sky list, SEDAC population data, FAA airspace — every
  overlay shows its source link in the methodology block.
- **Abstention is first-class.** "The data does not support
  a cluster here" is a legitimate output and the methodology
  documents non-findings alongside findings.
- **Don't lead the visitor.** No "AFBs are clearly correlated."
  Display the heatmap. Visitors draw their own conclusions.
- **Selection-bias caveats are surfaced, not hidden.** The
  sparse-population overlay needs a note about reporting-rate
  artifacts (fewer people = fewer reports != fewer events).

## Acceptance

- `/map` surfaces toggleable overlays: heatmap density, AFB
  proximity, era stratification (after display-date curation),
  test ranges, dark-sky, sparse-population.
- All feature data sources are open / public and cited.
- Pre-computation runs in CI; no live API dependencies.
- `/map/patterns.md` documents the abstention bar.
- At least one /finds entry documents a striking pattern with
  explicit non-causal framing.
- Atlas (UMAP) and Map (geographic) cross-link: atlas pins with
  location show a "→ map" affordance; map pins with semantic
  cluster show a "→ atlas" affordance.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Causal-claim drift in copy | High | Editorial bar enforced in `/map/patterns.md` and copy review. Operator final pass on every layer description. The /finds entry has to clear the abstention bar before publish. |
| Pattern claims that don't survive scrutiny | High | Hand-curate highlight cards; spot-check against primary sources before publishing. |
| Feature-layer data freshness (AFBs reorganize, ranges close) | Low | Layer data ships with `accessed_at` field; refresh per tranche. |
| Browser perf with multiple overlay layers active | Medium | Pre-compute aggressively; ship layers as binary GeoJSON or vector tiles; lazy-load on toggle; cap simultaneous layers if needed. |
| Tile-provider rate limits (OSM, MapTiler) | Medium | Investigate alongside the storage research thread; may need a paid tile relationship (MapTiler, Stadia) at scale. |
| Era-slice boundaries become editorial fights | Medium | Surface the choice in the editorial block; "we chose these eras because X" beats "these are the correct eras." Operator owns the call. |
| `/atlas` and `/map` confuse visitors | Low | Distinct nav labels, distinct copy on each landing page explaining what each surface does, cross-linking that says "this is the other one." |

## Out of scope (this plan)

- **3D / globe visualization.** Pretty; pays no research cost.
- **Real-time pin animation by date.** Replay is fine; constant
  animation is a gimmick.
- **User-submitted reports overlay.** This is a primary-source
  archive; community reporting is a separate (and big) discussion.
- **Cluster-claim AI annotations.** "What's interesting here?"
  is the visitor's question to answer; we don't pre-empt it with
  AI-generated narration.

## Open questions for operator

1. **Map library**: MapLibre GL JS (open-source, OSM tiles)
   vs. deck.gl (better for density heatmaps, more JS weight)
   vs. Mapbox (commercial dependency). Recommend MapLibre for
   the base; deck.gl as an overlay layer for heatmap density.

2. **Tile provider**: OSM raster tiles (free, rate-limited) vs.
   MapTiler or Stadia (paid, faster) vs. self-hosted vector
   tiles (most work, full control). Recommend OSM raster for
   Phase 1 ship, evaluate paid tier when traffic justifies.

3. **Era boundaries**: are the era slices (1947-1960, 1961-1980,
   1981-2000, 2001-2017, 2018-present) the right cuts? Could also
   do agency-era cuts (NICAP/APRO, Blue Book, NUFORC, post-2017
   ODNI). Worth a curation discussion before Phase 2.

4. **Naming**: `/map` (recommended) vs. `/incidents-map` vs.
   `/locations` vs. `/geography`. Final call before Phase 1
   ship.

5. **Nav slot**: "Incidents Map" added flat to nav (per
   visual-browse-surface plan's flat-nav posture), or grouped
   with `/atlas` under a parent? The plan's discussion concluded
   flat-nav-with-pruning is the right shape; this surface fits
   the same shape.

6. **Phase ordering vs. /gallery**: gallery is recommended
   priority 1 for the audience-surge framing. This Map surface
   sits at priority 3-4 in the current backlog. Order is fine
   as-is unless tranche signal changes.

## Notes on this plan's framing

This surface answers the same question the /atlas surface does
("what's in here?") through a fundamentally different lens. They
should ship as siblings, not as alternatives. Atlas = abstract
semantic similarity. Map = concrete geographic distribution.
Visitors will use both; researchers will lean on Map for spatial
questions and Atlas for thematic questions.
