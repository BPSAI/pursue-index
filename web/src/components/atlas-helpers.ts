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
 * Encode an ``AtlasPoint`` for regl-scatterplot.
 *
 * Slot 2 carries the category (color encoding); slot 3 carries an
 * "opacity-ish" value used to dim non-matching dots when a search
 * query is active. We default to 1.0 for the all-shown case; the
 * island toggles it via ``draw(points)`` re-uploads when the query
 * changes.
 */
export function pointToScatterplotRow(p: AtlasPoint): ScatterplotRow {
  return [p.x, p.y, agencyToCategory(p.agency), 1.0];
}

/**
 * Filter ``points`` to those whose lookup-resolved text contains
 * ``query`` (case-insensitive). Empty / whitespace-only ``query`` is
 * treated as "all match" so the caller can use the same code path
 * for "no filter" and "filter".
 */
export function filterIndicesByQuery(
  points: AtlasPoint[],
  query: string,
  lookup: (p: AtlasPoint) => string,
): number[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) {
    return points.map((_, i) => i);
  }
  const matches: number[] = [];
  for (let i = 0; i < points.length; i++) {
    const haystack = lookup(points[i]).toLowerCase();
    if (haystack.includes(trimmed)) {
      matches.push(i);
    }
  }
  return matches;
}

/**
 * Tiny seeded RNG (mulberry32). Keeps ``kmeansClusters`` deterministic
 * across browsers without pulling in a heavyweight RNG library.
 */
function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * k-means in 2D, used by the mobile fallback to group dots into list-view
 * buckets. Lloyd's algorithm with seeded init and a fixed iteration cap
 * — accuracy is not the win here, predictability across renders is.
 *
 * Returns one cluster label per point; labels are arbitrary but stable
 * for a fixed (points, k, seed) tuple.
 */
export function kmeansClusters(
  points: AtlasPoint[],
  k: number,
  seed: number,
  maxIterations = 50,
): number[] {
  if (points.length === 0) return [];
  const effectiveK = Math.min(k, points.length);
  const rng = mulberry32(seed);
  // Forgy init — pick k distinct random points as initial centroids.
  const indices = points.map((_, i) => i);
  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [indices[i], indices[j]] = [indices[j], indices[i]];
  }
  let centroids: [number, number][] = indices
    .slice(0, effectiveK)
    .map((i) => [points[i].x, points[i].y]);
  let labels = new Array(points.length).fill(0);
  for (let iter = 0; iter < maxIterations; iter++) {
    const next = assignLabels(points, centroids);
    const newCentroids = recomputeCentroids(points, next, effectiveK, centroids);
    if (sameLabels(labels, next) && centroidsClose(centroids, newCentroids)) {
      labels = next;
      centroids = newCentroids;
      break;
    }
    labels = next;
    centroids = newCentroids;
  }
  return labels;
}

function assignLabels(
  points: AtlasPoint[],
  centroids: [number, number][],
): number[] {
  const out = new Array(points.length).fill(0);
  for (let i = 0; i < points.length; i++) {
    let best = 0;
    let bestDist = Infinity;
    for (let c = 0; c < centroids.length; c++) {
      const dx = points[i].x - centroids[c][0];
      const dy = points[i].y - centroids[c][1];
      const d = dx * dx + dy * dy;
      if (d < bestDist) {
        bestDist = d;
        best = c;
      }
    }
    out[i] = best;
  }
  return out;
}

function recomputeCentroids(
  points: AtlasPoint[],
  labels: number[],
  k: number,
  prev: [number, number][],
): [number, number][] {
  const sums: [number, number][] = Array.from({ length: k }, () => [0, 0]);
  const counts = new Array(k).fill(0);
  for (let i = 0; i < points.length; i++) {
    const c = labels[i];
    sums[c][0] += points[i].x;
    sums[c][1] += points[i].y;
    counts[c]++;
  }
  return sums.map((s, c): [number, number] => {
    if (counts[c] === 0) return prev[c];
    return [s[0] / counts[c], s[1] / counts[c]];
  });
}

function sameLabels(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function centroidsClose(
  a: [number, number][],
  b: [number, number][],
  eps = 1e-6,
): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i][0] - b[i][0]) > eps) return false;
    if (Math.abs(a[i][1] - b[i][1]) > eps) return false;
  }
  return true;
}

function hexToRgba(hex: string, alpha = 1.0): RgbaColor {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  return [r, g, b, alpha];
}
