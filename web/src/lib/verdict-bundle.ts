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
  assertBundleSchema,
} from "./verdict-bundle-schema";

export { EXPECTED_BUNDLE_SCHEMA };

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

/**
 * Read the bundle with the schema-version check applied. Build-time
 * call only — Astro evaluates this at static-generation, so a bad
 * bundle fails the build rather than the deploy.
 */
export function loadVerdictBundle(): VerdictBundle {
  const bundle = bundleJson as VerdictBundle;
  assertBundleSchema(bundle);
  return bundle;
}
