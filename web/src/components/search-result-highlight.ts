/**
 * Pure helpers extracted from SearchIsland so the search-result rendering
 * pipeline (MiniSearch options + title/snippet highlighting) is unit-testable
 * without spinning up Preact.
 *
 * Three concerns live here:
 *   1. `buildSearchIndexOptions` — the canonical MiniSearch config used by
 *      *both* /search (SearchIsland) and /atlas (atlas-helpers). Tests
 *      instantiate MiniSearch with this exact shape so a regression in
 *      fuzzy/prefix/boost is caught here, not in the browser. The override
 *      hook is what keeps atlas (different doc shape, narrower storeFields)
 *      structurally locked to the same boost/prefix/no-fuzzy policy as
 *      /search — vaivora P0 on PR #29.
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
 * Subset of MiniSearch options callers may override on top of the shared
 * defaults. Anything outside this list (boost, prefix, fuzzy policy) is
 * intentionally NOT overridable — those are the cross-surface invariants
 * the factory exists to enforce.
 */
export interface SearchIndexOverrides {
  fields?: string[];
  storeFields?: string[];
}

/**
 * Canonical MiniSearch options for the page index, shared by /search and
 * /atlas. Pass `overrides` when the caller indexes a different doc shape
 * (atlas stores only a numeric render-array index, not card_id/page).
 *
 * Generic over the doc type so the same factory can build the production
 * /search index (PageDoc), the /atlas index (numeric-id docs), and test
 * fixtures without redeclaring the config.
 *
 * Notes on the choices:
 *   - `boost: { title: 2 }` — title matches outscore body matches.
 *   - `prefix: true` — keeps "uap" matching "uaps", "uap_d54", etc.
 *   - **No `fuzzy`** — operator decision 2026-05-10. Document search doesn't
 *     benefit from typo-tolerance, and fuzzy + prefix + AND was producing
 *     surprisingly broad results (e.g. "yellow area" returning docs that
 *     only loosely matched). Both /search and /atlas drop it — the shared
 *     factory is what keeps that guarantee structurally locked across
 *     surfaces, replacing the prior "must stay in lockstep" comment-only
 *     contract that PR #29 reviewers (vaivora P0) flagged as drift-prone.
 *
 * The factory only manages *construction* options. Per-search options
 * (e.g. `combineWith: "AND"`) stay at the call site where the query lives.
 */
export function buildSearchIndexOptions<T>(
  overrides?: SearchIndexOverrides,
): MiniSearchOptions<T> {
  return {
    fields: overrides?.fields ?? ["title", "text"],
    storeFields: overrides?.storeFields ?? ["card_id", "page", "title"],
    idField: "id",
    searchOptions: {
      boost: { title: 2 },
      prefix: true,
      // NO fuzzy — both /search and /atlas explicitly drop it. Do not add
      // it back here without flipping both surfaces; the override hook
      // above is intentionally narrow so this policy can't be quietly
      // bypassed by a per-call override.
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
