/**
 * Astro-side loader for ``web/src/data/verdict-bundle.json``.
 *
 * Imports the JSON at module scope (Astro/Vite handles the JSON
 * import at build time) and applies the schema-version gate from
 * the pure helper in ``verdict-bundle-schema.ts``. Three consumers
 * use this loader: ``altered.astro`` (listing),
 * ``altered/[card_id].astro`` (per-card detail), and
 * ``card/[card_id].astro`` (card-detail banner).
 *
 * Pure logic + tests live in ``verdict-bundle-schema.ts`` so Node's
 * native test runner can exercise the gate without import-attribute
 * gymnastics.
 */

import bundleJson from "../data/verdict-bundle.json";

import {
  EXPECTED_BUNDLE_SCHEMA,
  EXPECTED_VERDICT_SCHEMA,
  assertBundleSchema,
  assertBundleStatsConsistent,
} from "./verdict-bundle-schema.ts";

export { EXPECTED_BUNDLE_SCHEMA, EXPECTED_VERDICT_SCHEMA };

type VerdictRecord = {
  card_id: string;
  category?: string;
  rationale?: string;
  verdict?: string | null;
  decided_at?: string;
  operator?: string;
};

export type VerdictBundle = {
  bundle_schema_version: number;
  verdict_schema_version: number;
  generated_at: string;
  surface: string;
  stats: Record<string, number>;
  verdicts: Record<string, VerdictRecord>;
};

// Module-scope assertions: fire on first import, regardless of when
// or how a consumer calls loadVerdictBundle(). PR #79: the prior
// shape ran the asserts inside the loader
// function, so a future refactor that lazy-evaluated the call (e.g.
// inside a memoized helper) could have silently bypassed the gate.
// Module-scope runs them once at build time and caches the result.
const _bundle = bundleJson as VerdictBundle;
assertBundleSchema(_bundle);
assertBundleStatsConsistent(_bundle);

/**
 * Read the (already-validated) bundle. Build-time call only — Astro
 * evaluates the import at static-generation, so a bad bundle fails
 * the build rather than the deploy. The schema/stats asserts above
 * fire at module-load; this function is just a typed accessor.
 */
export function loadVerdictBundle(): VerdictBundle {
  return _bundle;
}
