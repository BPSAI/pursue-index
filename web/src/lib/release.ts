/**
 * Consolidated release constants — single source of truth for the
 * build-time corpus stats that several pages render.
 *
 * Historically the homepage, methodology page, and OG card art each
 * carried hand-typed numbers (`4,161` pages, `158` cards). When a new
 * tranche promoted those numbers drifted. This module reads the
 * manifest + snapshot index at build time so a single tranche
 * promotion updates everything that imports from here.
 *
 * Stats that are NOT in the manifest (release-01 date, OCR page count)
 * are recorded as frozen constants OR computed from `pages.json` at
 * build time. The OCR page count is the most expensive to derive
 * (pages.json is ~7MB), so we read it via Node's fs at build time
 * rather than ES-importing the full file into every consumer bundle.
 */

import raw from "../data/manifest.json" with { type: "json" };
import snapshotsIndex from "../../../data/manifests/snapshots/index.json" with { type: "json" };
import type { Manifest } from "../data/types";

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const manifest: Manifest = raw as Manifest;

// Frozen historical fact: PURSUE Release 01 was the Pentagon's
// 2026-05-08 first-wave release. Subsequent tranches are upstream
// metadata refreshes against the same source; the release-01 date
// is the citable origin event for the dataset as a whole.
const RELEASE_01_DATE = "2026-05-08";

interface SnapshotsIndex {
  snapshots: Array<{
    filename: string;
    csv_sha256: string;
    fetched_at: string;
    card_count: number;
  }>;
}

function trancheCount(): number {
  const idx = snapshotsIndex as SnapshotsIndex;
  // +1 for the current (live) manifest, which is not in snapshots/
  // because snapshots/ holds PRIOR tranches. The live one lives in
  // data/manifests/latest.json / web/src/data/manifest.json.
  return idx.snapshots.length + 1;
}

/**
 * Count OCR'd pages by reading public/data/pages.json at build time.
 *
 * We deliberately avoid ES-importing pages.json (it's ~7MB minified
 * and would bloat every consuming bundle). Instead we read the file
 * once at module-evaluation time on the server and cache the count.
 * On Cloudflare Pages the build runs in Node, so fs is available.
 *
 * If pages.json is missing (rare — only in fresh clones before the
 * first build), we fall back to a recorded last-known count so the
 * site still renders. The recorded value matches the corpus state as
 * of tranche c9cc83fcaf43 (2026-05-15).
 */
function countOcrPages(): number {
  const FALLBACK = 4161;
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    // web/src/lib/release.ts → web/public/data/pages.json
    const path = resolve(here, "../../public/data/pages.json");
    if (!existsSync(path)) return FALLBACK;
    const text = readFileSync(path, "utf8");
    // pages.json is a flat array of {card_id, page, text, …}. Count
    // entries with a non-empty text field. JSON.parse is fine — the
    // file is structured and a one-time build-time cost.
    const parsed = JSON.parse(text);
    if (!Array.isArray(parsed)) return FALLBACK;
    let n = 0;
    for (const row of parsed) {
      if (row && typeof row.text === "string" && row.text.length > 0) n++;
    }
    return n > 0 ? n : FALLBACK;
  } catch {
    return FALLBACK;
  }
}

/**
 * Count successfully-cleaned pages from public/data/pages-cleaned.json.
 *
 * Sprint 4b Theme E2: methodology.astro carried a literal `4,111 of
 * 4,161` prose that drifts on every full-corpus cleanup pass. The
 * right-hand number was already templated via `formatPageCount(RELEASE.ocrPageCount)`;
 * this constant adds a build-time source for the left-hand number so
 * the whole phrase tracks the manifest.
 *
 * A "successfully cleaned" page is one where the LLM cleanup produced
 * usable cleaned text AND no skip_reason was recorded. Pages skipped
 * due to content_filter / refusal / etc. preserve their original OCR
 * row in the mirror but `text` is empty + `skip_reason` is set; those
 * are excluded from this count. Falls back to a recorded last-known
 * value (matches the 2026-05-12 full-corpus pass state) if the file
 * is missing on first-clone builds.
 */
function countCleanedPages(): number {
  const FALLBACK = 4111;
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const path = resolve(here, "../../public/data/pages-cleaned.json");
    if (!existsSync(path)) return FALLBACK;
    const text = readFileSync(path, "utf8");
    const parsed = JSON.parse(text);
    // pages-cleaned.json shape: { meta: {...}, pages: [...] }
    if (!parsed || !Array.isArray(parsed.pages)) return FALLBACK;
    let n = 0;
    for (const row of parsed.pages) {
      if (
        row &&
        typeof row.text === "string" &&
        row.text.length > 0 &&
        !row.skip_reason
      ) {
        n++;
      }
    }
    return n > 0 ? n : FALLBACK;
  } catch {
    return FALLBACK;
  }
}

const currentTrancheId = manifest.csv_sha256;
const lastTrancheDate = new Date(manifest.fetched_at)
  .toISOString()
  .slice(0, 10);

export interface ReleaseConst {
  /** Full 64-char sha256 of the current manifest CSV (tranche id). */
  currentTrancheId: string;
  /** First 12 chars of currentTrancheId — citable short identifier. */
  currentTrancheIdShort: string;
  /** Number of cards in the current manifest. */
  cardCount: number;
  /** Number of OCR'd pages indexed in the current corpus. */
  ocrPageCount: number;
  /**
   * Number of OCR'd pages for which the LLM-cleanup pass produced
   * usable cleaned text. Always ≤ ocrPageCount; the difference is the
   * pages skipped (content_filter, refusal, etc.). See
   * `scripts/build_pages_cleaned.py::CLEANUP_SKIP_REASONS`.
   */
  cleanedPageCount: number;
  /** ISO date (YYYY-MM-DD) of the most recent tranche fetch. */
  lastTrancheDate: string;
  /** Frozen ISO date of PURSUE Release 01 (the canonical origin event). */
  release01Date: string;
  /** Total tranches captured (snapshot history + current). */
  trancheCount: number;
  /** Full ISO-8601 fetched_at timestamp for the current manifest. */
  fetchedAtIso: string;
}

export const RELEASE: ReleaseConst = {
  currentTrancheId,
  currentTrancheIdShort: currentTrancheId.slice(0, 12),
  cardCount: manifest.cards.length,
  ocrPageCount: countOcrPages(),
  cleanedPageCount: countCleanedPages(),
  lastTrancheDate,
  release01Date: RELEASE_01_DATE,
  trancheCount: trancheCount(),
  fetchedAtIso: manifest.fetched_at,
};

/** Format a card count with thousands separators (`1,234`). */
export function formatCardCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** Format an OCR page count with thousands separators (`4,161`). */
export function formatPageCount(n: number): string {
  return n.toLocaleString("en-US");
}
