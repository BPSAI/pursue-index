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

const _V2_CATEGORY_KEYS = ["re_processing", "procedural_correction", "content_change"] as const;

type StatsShape = {
  verdicts_emitted?: number;
  re_processing?: number;
  procedural_correction?: number;
  content_change?: number;
};

type VerdictRecordForStats = { category?: string };

/**
 * Build-time sanity that bundle.stats hasn't drifted from the actual
 * shape of bundle.verdicts. Cheap belt over the schema-version gate
 * — Vaivora PR #79 round-3 P2 #5 + Nayru round-4 P2 #4: pill counts
 * re-derive from rendered rows so stats isn't load-bearing in our
 * consumer, but the bundle is the public contract for external
 * consumers and a curate-side serializer bug that miscounts could
 * mislead them. Surface the mismatch loudly.
 *
 * Checks (each conditional on the relevant key being present so
 * older bundles without category breakdowns still parse):
 *   1. stats.verdicts_emitted matches Object.keys(verdicts).length
 *   2. stats.<category> matches count of verdicts with that category
 *   3. Σ(category counts) does not exceed verdicts_emitted (records
 *      can have categories outside the v2 vocab and those land in
 *      "unknown"; we don't enforce equality here, just that we
 *      didn't over-count)
 */
export function assertBundleStatsConsistent(bundle: {
  stats: StatsShape;
  verdicts: Record<string, VerdictRecordForStats>;
}): void {
  const verdicts = bundle.verdicts ?? {};
  const verdictsList = Object.values(verdicts);
  const actualTotal = verdictsList.length;
  const declared = bundle.stats?.verdicts_emitted;
  if (declared !== undefined && declared !== actualTotal) {
    throw new Error(
      `verdict-bundle.json stats.verdicts_emitted=${declared} but the ` +
      `bundle actually contains ${actualTotal} verdict record(s). The ` +
      `curate-side serializer in publish.py:_altered_stats has drifted ` +
      `from the verdict iterator. Re-run the bundle publish + spot-check ` +
      `the count before merging.`,
    );
  }
  for (const cat of _V2_CATEGORY_KEYS) {
    const declaredCat = bundle.stats?.[cat];
    if (declaredCat === undefined) continue;
    const actualCat = verdictsList.filter((v) => v.category === cat).length;
    if (declaredCat !== actualCat) {
      throw new Error(
        `verdict-bundle.json stats.${cat}=${declaredCat} but the bundle ` +
        `actually contains ${actualCat} record(s) with that category. The ` +
        `curate-side serializer's category counter has drifted from the ` +
        `record set. Re-publish the bundle and recheck.`,
      );
    }
  }
  const sumCategories = _V2_CATEGORY_KEYS.reduce(
    (n, k) => n + (bundle.stats?.[k] ?? 0),
    0,
  );
  if (sumCategories > actualTotal) {
    throw new Error(
      `verdict-bundle.json category counts sum to ${sumCategories} which ` +
      `exceeds verdicts_emitted=${actualTotal}. A record is being counted ` +
      `in more than one category bucket — curate publish.py drift.`,
    );
  }
}
