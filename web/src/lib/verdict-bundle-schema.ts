/**
 * Pure schema-gate helpers for verdict-bundle.json.
 *
 * Kept separate from ``verdict-bundle.ts`` (which imports the actual
 * JSON for Astro's build-time consumption) so Node's native test
 * runner can exercise the gate logic without needing JSON import
 * attributes. PR #79 — the gate has to be
 * testable in isolation so the contract is verifiable independently
 * of any committed bundle.
 *
 * Bump ``EXPECTED_BUNDLE_SCHEMA`` in lockstep with curate's
 * publish.py:bundle_schema_version when a future ALTR phase changes
 * the bundle contract.
 */

export const EXPECTED_BUNDLE_SCHEMA = 2;
export const EXPECTED_VERDICT_SCHEMA = 2;

/**
 * Single source of truth for the v2 category vocabulary across the
 * web consumer. PR #79: previously duplicated
 * in byte-display.ts's `VALID_V2_CATEGORIES`; the two lists had to
 * be updated in lockstep when curate added a category, otherwise
 * the render-gate and the schema-gate could drift independently.
 *
 * Pin in lockstep with curate's ``AlteredCategoryV2`` Literal in
 * ``src/curate/verdict_models.py``. Both ends of the cross-repo
 * contract must agree — see the source plan §Sequencing.
 */
export const V2_CATEGORIES = [
  "re_processing",
  "procedural_correction",
  "content_change",
] as const;

export type V2Category = (typeof V2_CATEGORIES)[number];
export const V2_CATEGORY_SET: ReadonlySet<string> = new Set(V2_CATEGORIES);

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
  // PR #79: gate the per-verdict schema too.
  // The two dimensions can drift independently (PR #3
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

// V2_CATEGORY_KEYS is the same list as V2_CATEGORIES; kept as an
// alias for the stats-check sites that read category names as
// object keys for clarity at the call site.
const V2_CATEGORY_KEYS = V2_CATEGORIES;

type StatsShape = {
  verdicts_emitted?: number;
  re_processing?: number;
  procedural_correction?: number;
  content_change?: number;
  unverified?: number;
};

type VerdictRecordForStats = { category?: string };

/**
 * Build-time sanity that bundle.stats hasn't drifted from the actual
 * shape of bundle.verdicts. Cheap belt over the schema-version gate
 * — pill counts
 * re-derive from rendered rows so stats isn't load-bearing in our
 * consumer, but the bundle is the public contract for external
 * consumers and a curate-side serializer bug that miscounts could
 * mislead them. Surface the mismatch loudly.
 *
 * Scope of gating: the v2 vocabulary keys
 * (re_processing / procedural_correction / content_change /
 * unverified) + verdicts_emitted. The v1-vocab one-cycle alias
 * keys (confirmed_content_change / false_positive / unsure /
 * pending) are emitted by curate-side publish.py as a backcompat
 * bridge and gated upstream there — INTENTIONALLY NOT re-checked
 * here. The v1 keys
 * exist for downstream consumers that haven't migrated to keying
 * on category. They'll be dropped from the bundle when curate
 * bumps to the next major (per the one-cycle policy in
 * curate/MIGRATION-v1-to-v2.md); the gate intentionally doesn't
 * pin them so dropping them doesn't break this consumer.
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
  for (const cat of V2_CATEGORY_KEYS) {
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
  const sumCategories = V2_CATEGORY_KEYS.reduce(
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
  // Close the closed-vocab contract.
  // The bundle and the consumer agree that `category` is in the v2
  // vocabulary; any value outside it indicates curate added a
  // category without bumping verdict_schema_version. Catch it here
  // before the page renders the record as "(unverified)" and the
  // listing pill silently miscategorizes it.
  const offenders: Array<{ card_id: string; category: string }> = [];
  for (const [cardId, v] of Object.entries(verdicts)) {
    if (v.category === undefined) continue;
    if (!V2_CATEGORY_SET.has(v.category)) {
      offenders.push({ card_id: cardId, category: v.category });
    }
  }
  if (offenders.length > 0) {
    throw new Error(
      `verdict-bundle.json contains ${offenders.length} record(s) with ` +
      `category values outside the v2 vocabulary ` +
      `${JSON.stringify([...V2_CATEGORIES])}: ` +
      `${JSON.stringify(offenders.slice(0, 5))}${offenders.length > 5 ? "..." : ""}. ` +
      `Either: (a) curate.AlteredCategoryV2 was extended without bumping ` +
      `EXPECTED_VERDICT_SCHEMA — coordinate the bump across repos; or ` +
      `(b) a record has corrupted category data — re-author through the ` +
      `curate web UI.`,
    );
  }
  // Gate stats.unverified the same as
  // the categorical counters. Today the bundle ships
  // stats.unverified for cards in queue without a verdict (curate-
  // side semantic). External consumers reading the bundle directly
  // shouldn't see a number that doesn't match what's actually in
  // the verdicts dict + queue context. Conditional on presence so
  // older bundles still parse.
  const declaredUnverified = bundle.stats?.unverified;
  if (declaredUnverified !== undefined) {
    // The bundle's `unverified` is "queue rows without an emitted
    // verdict" — curate computes it from byte-history.json vs
    // verdicts. The consumer doesn't have queue context here, but
    // we CAN sanity-check that stats.unverified + verdicts_emitted
    // doesn't exceed any plausible queue size embedded in the
    // bundle. Cheapest gate: assert unverified is a non-negative
    // integer. Anything more requires cross-referencing
    // byte-history.json, which is the symmetric-drift test's job.
    if (!Number.isInteger(declaredUnverified) || declaredUnverified < 0) {
      throw new Error(
        `verdict-bundle.json stats.unverified=${declaredUnverified} ` +
        `must be a non-negative integer.`,
      );
    }
  }
}
