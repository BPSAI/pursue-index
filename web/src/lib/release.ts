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
 * Read a JSON file relative to this module and count rows in a list
 * (either a top-level array OR a `{pages: [...]}` shape) that satisfy
 * `predicate`. Returns `fallback` on any failure: file missing, parse
 * error, list-shape mismatch, predicate-matched-zero-rows.
 *
 * nayru P2#4: extracted from the previously-near-duplicate
 * `countOcrPages` / `countCleanedPages` so the file-read +
 * fallback-on-error scaffolding lives in one place. New builders that
 * count manifest-derived rows should plumb through here.
 *
 * `listGetter` describes how to find the list inside the parsed JSON:
 * pages.json is itself an array, pages-cleaned.json has the list under
 * `.pages`. Callers pass the lookup so the helper stays shape-agnostic.
 */
function countMatchingRows(
  relativePath: string,
  listGetter: (parsed: unknown) => unknown,
  predicate: (row: unknown) => boolean,
  fallback: number,
): number {
  // 2026-05-22 hotfix: previously this resolved `relativePath` against
  // `import.meta.url` (the module location). Under Astro's Vite-driven
  // build, `release.ts` gets compiled + executed from a chunk path inside
  // `node_modules/.astro/` or `dist/_astro/`, so the relative-to-module
  // lookup landed at a path that didn't exist and silently fell back to
  // the literal — leaving the homepage showing 4,161 instead of the live
  // 4,289 across the entire tranche-2 deploy.
  //
  // The build always runs from the `web/` directory (npm run build
  // changes cwd before invoking astro), so resolving against
  // `process.cwd()` is reliable. The import.meta.url path is kept as a
  // secondary fallback for the rare case this module is consumed from a
  // tool that runs from a different cwd.
  const candidates = [
    resolve(process.cwd(), relativePath.replace(/^\.\.\/\.\.\//, "")),
    resolve(dirname(fileURLToPath(import.meta.url)), relativePath),
  ];
  for (const path of candidates) {
    try {
      if (!existsSync(path)) continue;
      const text = readFileSync(path, "utf8");
      const parsed = JSON.parse(text);
      const list = listGetter(parsed);
      if (!Array.isArray(list)) continue;
      let n = 0;
      for (const row of list) {
        if (predicate(row)) n++;
      }
      if (n > 0) return n;
    } catch {
      // fall through to the next candidate
    }
  }
  return fallback;
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
  // web/src/lib/release.ts → web/public/data/pages.json.
  // pages.json is a flat array of {card_id, page, text, …}; count
  // entries with a non-empty text field.
  return countMatchingRows(
    "../../public/data/pages.json",
    (parsed) => parsed,
    (row) => {
      if (!row || typeof row !== "object") return false;
      const r = row as { text?: unknown };
      return typeof r.text === "string" && r.text.length > 0;
    },
    4161,
  );
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
  // pages-cleaned.json shape: { meta: {...}, pages: [...] }
  return countMatchingRows(
    "../../public/data/pages-cleaned.json",
    (parsed) => {
      if (parsed && typeof parsed === "object" && "pages" in parsed) {
        return (parsed as { pages: unknown }).pages;
      }
      return undefined;
    },
    (row) => {
      if (!row || typeof row !== "object") return false;
      const r = row as { text?: unknown; skip_reason?: unknown };
      return (
        typeof r.text === "string" && r.text.length > 0 && !r.skip_reason
      );
    },
    4111,
  );
}

const currentTrancheId = manifest.csv_sha256;
const lastTrancheDate = new Date(manifest.fetched_at)
  .toISOString()
  .slice(0, 10);

export interface ReleaseConst {
  /**
   * Site version, source-of-truth for the "Research preview (vX.Y.Z)"
   * banner + any other UI string that references the deployed release.
   * Bumped manually as part of the release runbook (Phase 0 of the
   * site-release-checklist: every minor tranche-promote bumps minor,
   * patches bump patch). Pairs with the git tag pushed alongside.
   */
  version: string;
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
  /**
   * Per-engine page count breakdown across the corpus. Used by the
   * /methodology page to surface the actual surya / llm-anthropic split
   * instead of a hand-typed "~15%" approximation that drifted across
   * tranches. Built from pages.json at module-eval time.
   */
  ocrEngineCounts: Record<string, number>;
}

function countByEngine(): Record<string, number> {
  // Same path-resolution discipline as countOcrPages — process.cwd()
  // first, import.meta.url fallback — so Astro's Vite chunking doesn't
  // strand the lookup.
  const fallback: Record<string, number> = { surya: 3654, "llm-anthropic": 635 };
  const candidates = [
    resolve(process.cwd(), "public/data/pages.json"),
    resolve(dirname(fileURLToPath(import.meta.url)), "../../public/data/pages.json"),
  ];
  for (const path of candidates) {
    try {
      if (!existsSync(path)) continue;
      const text = readFileSync(path, "utf8");
      const parsed = JSON.parse(text) as Array<{ engine?: string; text?: string }>;
      if (!Array.isArray(parsed)) continue;
      const counts: Record<string, number> = {};
      for (const row of parsed) {
        if (!row || typeof row !== "object") continue;
        if (typeof row.text !== "string" || row.text.length === 0) continue;
        const e = typeof row.engine === "string" ? row.engine : "unknown";
        counts[e] = (counts[e] ?? 0) + 1;
      }
      if (Object.keys(counts).length === 0) continue;
      return counts;
    } catch {
      // fall through
    }
  }
  return fallback;
}

export const RELEASE: ReleaseConst = {
  // Bumped manually per release. v1.2.2 ships corpus-wide Sonnet 4.6
  // OCR (3,500+ pages re-OCR'd via card-level concurrency), Haiku 4.5
  // clean pass on the new text, Voyage-3 re-embed, and retirement of
  // the /altered/ surface after operator review confirmed 0/70
  // confirmed content edits across the byte-changed candidates.
  version: "v1.2.2",
  currentTrancheId,
  currentTrancheIdShort: currentTrancheId.slice(0, 12),
  cardCount: manifest.cards.length,
  ocrPageCount: countOcrPages(),
  cleanedPageCount: countCleanedPages(),
  lastTrancheDate,
  release01Date: RELEASE_01_DATE,
  trancheCount: trancheCount(),
  fetchedAtIso: manifest.fetched_at,
  ocrEngineCounts: countByEngine(),
};

/** Format a card count with thousands separators (`1,234`). */
export function formatCardCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** Format an OCR page count with thousands separators (`4,161`). */
export function formatPageCount(n: number): string {
  return n.toLocaleString("en-US");
}
