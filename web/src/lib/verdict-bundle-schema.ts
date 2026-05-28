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
export const EXPECTED_VERDICT_SCHEMA = 2;

export function assertBundleSchema(bundle: {
  bundle_schema_version: number;
  verdict_schema_version?: number;
}): void {
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
  // Vaivora PR #79 round-3 P2 #4: gate the per-verdict schema too.
  // The two dimensions can drift independently (vaivora PR #3 P2
  // in pursue-curate); a future curate change that bumps only the
  // inner schema (e.g., a new mandatory per-verdict field) would
  // otherwise slip through the bundle-version gate.
  if (
    bundle.verdict_schema_version !== undefined &&
    bundle.verdict_schema_version !== EXPECTED_VERDICT_SCHEMA
  ) {
    throw new Error(
      `verdict-bundle.json verdict_schema_version is ` +
      `${bundle.verdict_schema_version}; consumer expects ` +
      `${EXPECTED_VERDICT_SCHEMA}. The per-record verdict shape changed; ` +
      `audit the VerdictRecord type in verdict-bundle.ts and any ` +
      `consumer that reads optional fields, then bump ` +
      `EXPECTED_VERDICT_SCHEMA here.`,
    );
  }
}

/**
 * Build-time sanity that bundle.stats.verdicts_emitted hasn't drifted
 * from the actual number of verdicts shipped. Cheap belt over the
 * schema-version gate — Vaivora PR #79 round-3 P2 #5: now that pill
 * counts re-derive from rendered rows, bundle.stats is no longer
 * load-bearing in any consumer, but a curate-side serializer bug
 * that miscounts could still mislead any external consumer reading
 * the bundle. Surface the mismatch loudly.
 */
export function assertBundleStatsConsistent(bundle: {
  stats: { verdicts_emitted?: number };
  verdicts: Record<string, unknown>;
}): void {
  const declared = bundle.stats?.verdicts_emitted;
  const actual = Object.keys(bundle.verdicts ?? {}).length;
  if (declared !== undefined && declared !== actual) {
    throw new Error(
      `verdict-bundle.json stats.verdicts_emitted=${declared} but the ` +
      `bundle actually contains ${actual} verdict record(s). The curate-side ` +
      `serializer in publish.py:_altered_stats has drifted from the verdict ` +
      `iterator. Re-run the bundle publish + spot-check the count before ` +
      `merging.`,
    );
  }
}
