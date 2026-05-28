/**
 * Pure schema-gate helpers for verdict-bundle.json.
 *
 * Kept separate from ``verdict-bundle.ts`` (which imports the actual
 * JSON for Astro's build-time consumption) so Node's native test
 * runner can exercise the gate logic without needing JSON import
 * attributes. Vaivora PR #79 round-2 P1-2 — the gate has to be
 * testable in isolation so the contract is verifiable independently
 * of any committed bundle.
 *
 * Bump ``EXPECTED_BUNDLE_SCHEMA`` in lockstep with curate's
 * publish.py:bundle_schema_version when a future ALTR phase changes
 * the bundle contract.
 */

export const EXPECTED_BUNDLE_SCHEMA = 2;

export function assertBundleSchema(bundle: { bundle_schema_version: number }): void {
  if (bundle.bundle_schema_version !== EXPECTED_BUNDLE_SCHEMA) {
    throw new Error(
      `verdict-bundle.json bundle_schema_version is ` +
      `${bundle.bundle_schema_version}; consumer expects ` +
      `${EXPECTED_BUNDLE_SCHEMA}. Update altered.astro + ` +
      `altered/[card_id].astro + card/[card_id].astro banner to ` +
      `match the new bundle shape, then bump EXPECTED_BUNDLE_SCHEMA ` +
      `in web/src/lib/verdict-bundle-schema.ts.`,
    );
  }
}
