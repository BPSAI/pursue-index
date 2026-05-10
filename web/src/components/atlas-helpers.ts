/**
 * Pure helpers for the AtlasIsland.
 *
 * Split from the island so each piece is unit-testable without
 * spinning up regl-scatterplot. The island wires these into the
 * component lifecycle and the canvas; everything in here is data
 * transforms (no DOM, no WebGL).
 *
 * Color palette comes from ``web/src/styles/global.css`` — the
 * ``--color-signal-*`` tokens. Numbers below are the hex values from
 * that file converted to floats; if the tokens move, update both.
 */

import MiniSearch from "minisearch";
import { buildSearchIndexOptions } from "./search-result-highlight.ts";

/** Wire shape of one point in ``atlas-layout.json``. */
export interface AtlasPoint {
  card_id: string;
  page: number;
  x: number;
  y: number;
  agency: string;
}

/**
 * Canonical agency ordering. The category index passed to
 * regl-scatterplot is the index into this array, so reordering it
 * silently re-colors deployed builds — only append, never permute.
 */
export const AGENCY_ORDER = [
  "Department of War",
  "FBI",
  "NASA",
  "Department of State",
] as const;

/** RGB triplet (0..1) plus alpha (0..1) — regl-scatterplot color shape. */
export type RgbaColor = [number, number, number, number];

/**
 * Map an agency string to its category index.
 * Unknown agencies land at ``AGENCY_ORDER.length`` (the trailing slot).
 */
export function agencyToCategory(agency: string): number {
  const idx = AGENCY_ORDER.indexOf(agency as (typeof AGENCY_ORDER)[number]);
  return idx === -1 ? AGENCY_ORDER.length : idx;
}

/**
 * One color per category index, in the same order as ``AGENCY_ORDER``.
 * Trailing entry is the neutral fallback for "UNKNOWN".
 *
 * Hex sources (mirrored from global.css):
 *   - Department of War   → signal-green   #a4ff5a
 *   - FBI                 → signal-cyan    #5fd4ff
 *   - NASA                → signal-violet  #b78fff
 *   - Department of State → signal-amber   #ffc857
 *   - UNKNOWN             → text-dim       #6b7783
 */
export function categoryColors(): RgbaColor[] {
  return [
    hexToRgba("#a4ff5a"),
    hexToRgba("#5fd4ff"),
    hexToRgba("#b78fff"),
    hexToRgba("#ffc857"),
    hexToRgba("#6b7783"),
  ];
}

/** A single regl-scatterplot row: ``[x, y, category, value]``. */
export type ScatterplotRow = [number, number, number, number];

/**
 * Dim opacity applied to non-matching points when a search filter is
 * active. Lives at index 0 of the ``opacity`` lookup table passed to
 * ``createScatterplot``.
 */
export const DIM_OPACITY = 0.15;

/**
 * Full opacity for matched / unfiltered points. Lives at index 1 of the
 * ``opacity`` lookup table passed to ``createScatterplot``.
 */
export const FULL_OPACITY = 1.0;

/**
 * Encode an ``AtlasPoint`` for regl-scatterplot.
 *
 * Slot 2 carries the category (color encoding via ``colorBy: "valueA"``);
 * slot 3 carries a SELECTOR INDEX (0 or 1) into the ``opacity`` lookup
 * table on the ``createScatterplot`` config — NOT a raw opacity value.
 *
 * Why an index, not the opacity itself: regl-scatterplot's shader does
 * ``floor(state.w * opacityMultiplicator)`` to index a 1D texture built
 * from the ``opacity`` config array. With ``opacity: [DIM_OPACITY,
 * FULL_OPACITY]`` the multiplicator is 1, so ``state.w === 0`` →
 * ``opacity[0]`` (dim) and ``state.w === 1`` → ``opacity[1]`` (full).
 * Packing the index here (rather than a raw 0.15 / 1.0) keeps the dim
 * value in one place (the ``opacity`` lookup) and avoids the trap where
 * a future maintainer changes ``DIM_OPACITY`` to 0.5 and discovers that
 * ``floor(0.5 * 1) = 0`` happens to still floor to dim, but ``0.7``
 * silently floors to dim too.
 *
 * Default ``opacityIndex`` is 1 (bright) so the bare
 * ``points.map(pointToScatterplotRow)`` initial-draw call site renders
 * all-shown; the search-redraw effect passes 0 for non-matching points.
 * Using the same row builder in both paths keeps the tuple shape (and
 * the ``colorBy`` / ``opacityBy`` slot semantics) in one place — vaivora P2.
 */
export function pointToScatterplotRow(
  p: AtlasPoint,
  opacityIndex: 0 | 1 = 1,
): ScatterplotRow {
  return [p.x, p.y, agencyToCategory(p.agency), opacityIndex];
}

/**
 * Build the deep-link URL for a card / page hit.
 *
 * Site-wide deep-link contract: the query slot is reserved for ``?q=…``
 * (the search-term carry-through used by ``Cite.astro`` and
 * ``CardOcrIsland`` for highlight). Atlas links MUST emit fragment-only
 * URLs — adding ``?page=N`` would squat on that slot, conflict with
 * future query carry-through, and bloat shared URLs.
 *
 * Encodes ``cardId`` defensively (``encodeURIComponent``); today's IDs
 * are sha256[:16] hex so the encode is a no-op, but this hardens any
 * future flow that surfaces a non-hex token through the same helper
 * (laverna SEC-003).
 */
export function buildCardHref(base: string, cardId: string, page: number): string {
  return `${base}/card/${encodeURIComponent(cardId)}#page-${page}`;
}

/**
 * MiniSearch instance for atlas search. Indexed once over all atlas
 * points so each keystroke runs a search rather than a fresh build.
 *
 * Configuration is sourced from ``buildSearchIndexOptions`` in
 * ``search-result-highlight.ts`` — the same factory ``SearchIsland`` uses
 * — so the same input lights up the same set of rows on /search and
 * /atlas (vaivora P1: search-relevance divergence; vaivora P0 on PR #29:
 * the prior comment-only contract was drift-prone, the shared factory
 * makes the lockstep structural). Atlas overrides ``storeFields`` to keep
 * only the render-array index, since it doesn't need card_id/page on the
 * stored doc — the island re-keys matches back to its own render order.
 *
 * Per-search options (``combineWith: "AND"``) live at the call site below;
 * the factory only manages construction-time options.
 */
export interface AtlasMiniSearch {
  search(query: string): number[];
  size: number;
}

export function buildAtlasMiniSearch(
  points: AtlasPoint[],
  lookup: (p: AtlasPoint) => { title?: string; text?: string } | undefined,
): AtlasMiniSearch {
  type AtlasDoc = { id: number; title: string; text: string };
  const ms = new MiniSearch<AtlasDoc>(
    buildSearchIndexOptions<AtlasDoc>({ storeFields: ["id"] }),
  );
  const docs = points.map((p, i) => {
    const r = lookup(p) ?? {};
    return { id: i, title: r.title ?? "", text: r.text ?? "" };
  });
  ms.addAll(docs);
  return {
    size: points.length,
    search(query: string): number[] {
      const trimmed = query.trim();
      if (!trimmed) return points.map((_, i) => i);
      const hits = ms.search(trimmed, { combineWith: "AND" });
      return hits.map((h) => Number(h.id));
    },
  };
}

/**
 * Run a MiniSearch query against an atlas index, mapping hits back to
 * point indices in the render array. Empty / whitespace-only queries
 * return all indices so callers can use the same code path for
 * "no filter" and "filter".
 */
export function searchIndicesViaMiniSearch(
  index: AtlasMiniSearch,
  query: string,
): number[] {
  return index.search(query);
}

function hexToRgba(hex: string, alpha = 1.0): RgbaColor {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  return [r, g, b, alpha];
}
