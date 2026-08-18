import { describe, test } from "node:test";
import assert from "node:assert/strict";

// Tests target the pure-logic file so Node's test runner doesn't
// need import attributes for JSON. The Astro-side loader
// (verdict-bundle.ts) wires this assert in at module scope and is
// covered by `npm run build`.
import {
  EXPECTED_BUNDLE_SCHEMA,
  EXPECTED_VERDICT_SCHEMA,
  V2_CATEGORIES,
  V2_CATEGORY_SET,
  assertBundleSchema,
  assertBundleStatsConsistent,
} from "./verdict-bundle-schema.ts";

describe("assertBundleSchema — gate", () => {
  test("EXPECTED_BUNDLE_SCHEMA pins the consumer's expected version", () => {
    // Pinned so bumping the bundle without bumping consumers fails
    // this test as a tripwire. Bump in lockstep with curate's
    // publish.py:bundle_schema_version.
    assert.equal(EXPECTED_BUNDLE_SCHEMA, 2);
  });

  test("throws naming both the actual and expected version", () => {
    try {
      assertBundleSchema({ bundle_schema_version: 99 });
      assert.fail("expected schema assert to throw");
    } catch (e) {
      const msg = String(e);
      assert.match(msg, /99/);
      assert.match(msg, /expects 2/);
      // Error names the consumer files that need updating.
      assert.match(msg, /altered\.astro/);
      assert.match(msg, /altered\/\[card_id\]\.astro/);
    }
  });

  test("accepts the expected version", () => {
    assert.doesNotThrow(() =>
      assertBundleSchema({ bundle_schema_version: EXPECTED_BUNDLE_SCHEMA }),
    );
  });

  test("rejects bundle_schema_version=1 (curate's pre-vocab version)", () => {
    assert.throws(() => assertBundleSchema({ bundle_schema_version: 1 }));
  });

  test("rejects bundle_schema_version=3 (a hypothetical future bump)", () => {
    // Pinned so a v3 bundle landing without a consumer rewrite
    // fails the build loudly with a clear remediation pointer.
    assert.throws(() => assertBundleSchema({ bundle_schema_version: 3 }));
  });

  test("verdict_schema_version is gated when present", () => {
    // Prior gate only checked the
    // bundle envelope version. A curate change that bumps only
    // the per-record schema (new mandatory field) would have
    // slipped past.
    assert.throws(() =>
      assertBundleSchema({ bundle_schema_version: 2, verdict_schema_version: 3 }),
    );
    assert.throws(() =>
      assertBundleSchema({ bundle_schema_version: 2, verdict_schema_version: 1 }),
    );
  });

  test("verdict_schema_version absent is tolerated (back-compat)", () => {
    // Older bundles may not carry the per-record version field.
    assert.doesNotThrow(() =>
      assertBundleSchema({ bundle_schema_version: 2 }),
    );
  });

  test("EXPECTED_VERDICT_SCHEMA pins the per-record expected version", () => {
    assert.equal(EXPECTED_VERDICT_SCHEMA, 2);
  });
});

describe("assertBundleStatsConsistent — serializer drift detector", () => {
  test("accepts matching declared + actual counts", () => {
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 2 },
        verdicts: { a: {}, b: {} },
      }),
    );
  });

  test("throws when declared > actual (extra count)", () => {
    try {
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 3 },
        verdicts: { a: {} },
      });
      assert.fail("expected stats drift to throw");
    } catch (e) {
      assert.match(String(e), /verdicts_emitted=3/);
      assert.match(String(e), /actually contains 1/);
    }
  });

  test("throws when declared < actual (missing count)", () => {
    assert.throws(() =>
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 0 },
        verdicts: { a: {}, b: {} },
      }),
    );
  });

  test("tolerates missing verdicts_emitted (older bundles)", () => {
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: {},
        verdicts: { a: {}, b: {} },
      }),
    );
  });

  test("category breakdown matches verdict records", () => {
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: {
          verdicts_emitted: 3,
          re_processing: 2,
          procedural_correction: 1,
          content_change: 0,
        },
        verdicts: {
          a: { category: "re_processing" },
          b: { category: "re_processing" },
          c: { category: "procedural_correction" },
        },
      }),
    );
  });

  test("throws when category bucket overstates", () => {
    // A serializer that miscategorizes
    // (bumps procedural_correction without changing a record's
    // category field) now fails the gate.
    try {
      assertBundleStatsConsistent({
        stats: { procedural_correction: 5 },
        verdicts: { a: { category: "procedural_correction" } },
      });
      assert.fail("expected category drift to throw");
    } catch (e) {
      assert.match(String(e), /procedural_correction=5/);
      assert.match(String(e), /actually contains 1/);
    }
  });

  test("throws when category counts sum > verdicts_emitted (double-count)", () => {
    assert.throws(() =>
      assertBundleStatsConsistent({
        stats: {
          verdicts_emitted: 2,
          re_processing: 2,
          procedural_correction: 2,
          content_change: 0,
        },
        verdicts: {
          a: { category: "re_processing" },
          b: { category: "re_processing" },
        },
      }),
    );
  });

  test("tolerates missing category counters (older bundles, partial stats)", () => {
    // Conditional-on-presence: bundles that only carry
    // verdicts_emitted still pass the gate.
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 1 },
        verdicts: { a: { category: "re_processing" } },
      }),
    );
  });

  test("rejects record with unknown category value (closed-vocab gate)", () => {
    // Closes the gap where a curate-
    // side addition (e.g. `editorial_change`) without a schema
    // version bump would have rendered as "(unverified)" instead
    // of failing the build.
    try {
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 1 },
        verdicts: { a: { category: "editorial_change" } },
      });
      assert.fail("expected unknown category to throw");
    } catch (e) {
      assert.match(String(e), /editorial_change/);
      assert.match(String(e), /EXPECTED_VERDICT_SCHEMA/);
    }
  });

  test("accepts records with undefined category (v1-leakage allowed)", () => {
    // Defense-in-depth: a v1-shaped record without a category
    // field is allowed (it lands in the consumer's `unverified`
    // bucket). The vocab gate only fires for records that DECLARE
    // a category outside the v2 vocab.
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: { verdicts_emitted: 1 },
        verdicts: { a: {} },
      }),
    );
  });

  test("rejects stats.unverified that's not a non-negative integer", () => {
    assert.throws(() =>
      assertBundleStatsConsistent({
        stats: { unverified: -1 },
        verdicts: {},
      }),
    );
    assert.throws(() =>
      assertBundleStatsConsistent({
        // @ts-expect-error testing runtime guard against wrong type
        stats: { unverified: 1.5 },
        verdicts: {},
      }),
    );
  });

  test("accepts stats.unverified=0 (current bundle state)", () => {
    assert.doesNotThrow(() =>
      assertBundleStatsConsistent({
        stats: { unverified: 0, verdicts_emitted: 1 },
        verdicts: { a: { category: "re_processing" } },
      }),
    );
  });
});

describe("V2_CATEGORIES — single source of truth", () => {
  test("V2_CATEGORIES is the three v2 vocab values", () => {
    // Tripwire so a curate-side
    // category addition without coordinated update here fails
    // the test, drawing attention to the cross-repo lockstep
    // contract.
    assert.deepEqual([...V2_CATEGORIES], [
      "re_processing",
      "procedural_correction",
      "content_change",
    ]);
  });

  test("V2_CATEGORY_SET is consistent with V2_CATEGORIES", () => {
    assert.equal(V2_CATEGORY_SET.size, V2_CATEGORIES.length);
    for (const c of V2_CATEGORIES) {
      assert.ok(V2_CATEGORY_SET.has(c));
    }
  });
});
