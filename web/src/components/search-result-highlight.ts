/**
 * Pure helpers extracted from SearchIsland so the search-result rendering
 * pipeline (MiniSearch options + title/snippet highlighting) is unit-testable
 * without spinning up Preact.
 *
 * Three concerns live here:
 *   1. `buildSearchIndexOptions` — the canonical MiniSearch config used by
 *      SearchIsland. Tests instantiate MiniSearch with this exact shape so
 *      a regression in fuzzy/prefix/boost is caught here, not in the browser.
 *   2. `highlightSegments` — thin wrapper over `splitWithRegex` for use in
 *      JSX (title and snippet both go through it). Re-exported so the call
 *      site has one import for "render this string with highlights".
 *   3. `hasMatchSegment` — detects when a built segment list contains zero
 *      match segments. Used by SearchIsland to suppress an unhighlighted
 *      snippet block when the hit was title-only (the snippet would
 *      otherwise look like a "no match here" slice of body text).
 */

import type { Options as MiniSearchOptions } from "minisearch";
import { splitWithRegex, type Segment } from "./highlight.ts";

/**
 * Canonical MiniSearch options for SearchIsland's page index.
 *
 * Generic over the doc type so the same factory can build the production
 * index (PageDoc) and any test fixtures without redeclaring the config.
 *
 * Notes on the choices:
 *   - `boost: { title: 2 }` — title matches outscore body matches.
 *   - `prefix: true` — keeps "uap" matching "uaps", "uap_d54", etc.
 *   - **No `fuzzy`** — document search doesn't benefit from typo-tolerance,
 *     and fuzzy + prefix + AND was producing surprisingly broad results
 *     (e.g. "yellow area" returning docs that only loosely matched).
 */
export function buildSearchIndexOptions<T>(): MiniSearchOptions<T> {
  return {
    fields: ["title", "text"],
    storeFields: ["card_id", "page", "title"],
    idField: "id",
    searchOptions: {
      boost: { title: 2 },
      prefix: true,
    },
  };
}

/** Split `text` into highlight segments using `regex` (null => single text). */
export function highlightSegments(
  text: string,
  regex: RegExp | null,
): Segment[] {
  return splitWithRegex(text, regex);
}

/** True iff at least one segment is a match — used to gate snippet rendering. */
export function hasMatchSegment(segments: Segment[]): boolean {
  return segments.some((s) => s.kind === "match");
}
