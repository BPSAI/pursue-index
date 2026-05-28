import { describe, test } from "node:test";
import assert from "node:assert/strict";

// Tests target the pure-logic file so Node's test runner doesn't
// need import attributes for JSON. The Astro-side loader
// (verdict-bundle.ts) wires this assert in at module scope and is
// covered by `npm run build`.
import {
  EXPECTED_BUNDLE_SCHEMA,
  assertBundleSchema,
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
});
