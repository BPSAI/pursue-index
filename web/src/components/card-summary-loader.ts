/**
 * Runtime loader for the cards-summary payload that CardExplorer
 * hydrates with.
 *
 * Dropping the inline `cards` prop on the homepage
 * cut DOM size from 695 KB → 26 KB. CardExplorer now fetches
 * `web/public/data/cards-summary.json` on hydration. The Worker's
 * Cache-Control policy (`worker/index.js::CACHE_POLICY`, the
 * `/data/*.json` rule) does the freshness work: 1h fresh + 24h
 * stale-while-revalidate.
 *
 * This helper lives in its own module so the fetch behavior (URL
 * shape, cache mode, failure-mode degradation) is unit-testable under
 * `node --test` without spinning up a Preact renderer. See
 * `card-summary-loader.test.ts`.
 */

import type { CardMetadata } from "../data/types";

/**
 * Fetch options for the cards-summary request.
 *
 * `cache: "default"` lets the browser
 * honor the Worker's Cache-Control header verbatim — the 1h-fresh +
 * 24h-SWR policy stamped by `withCacheHeaders` on the `/data/*.json`
 * rule. `"force-cache"` ignores SWR and silently pins
 * stale payloads across tranche promotions, which would be wrong
 * here: the file changes on every tranche.
 */
export const CARD_SUMMARY_FETCH_OPTIONS: RequestInit = {
  cache: "default",
};

/**
 * Fetch the cards-summary payload built by
 * `web/scripts/build_cards_summary.mjs`.
 *
 * Resolves to `[]` on any failure (network rejection, non-2xx, body
 * not an array). The empty-array sentinel keeps the UI rendering the
 * filter chrome + `[NO MATCH]` block instead of hanging on an
 * exception. Callers that need to distinguish "fetch hasn't resolved
 * yet" from "fetch resolved empty" should treat the initial value as
 * `null` and only call this helper inside an effect.
 */
export async function loadCardsSummary(
  base: string,
): Promise<CardMetadata[]> {
  try {
    const res = await fetch(
      `${base}/data/cards-summary.json`,
      CARD_SUMMARY_FETCH_OPTIONS,
    );
    if (!res.ok) return [];
    const data = (await res.json()) as CardMetadata[];
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}
