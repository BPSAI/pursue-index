/**
 * JSON-LD is written into an inline `<script type="application/ld+json">`,
 * and card JSON-LD carries upstream strings (titles, agencies, filenames).
 * The serializer must emit nothing an HTML parser could read as markup
 * inside a script element, while staying lossless JSON.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { safeJsonLd } from "./json-ld-safe.ts";

const HOSTILE = {
  "@type": "CreativeWork",
  name: "Report </SCRIPT><img src=x onerror=alert(1)>",
  alternateName: "<!--<script>",
  description: "A & B > C < D \u2028 line \u2029 para",
  nested: { headline: "x</script>y" },
};

test("no '<', '>' or '&' survives into the serialized payload", () => {
  const out = safeJsonLd(HOSTILE);
  assert.ok(!out.includes("<"), out);
  assert.ok(!out.includes(">"), out);
  assert.ok(!out.includes("&"), out);
});

test("U+2028 and U+2029 are escaped", () => {
  const out = safeJsonLd(HOSTILE);
  assert.ok(!out.includes("\u2028") && !out.includes("\u2029"), out);
});

test("the payload parses back to the identical value", () => {
  assert.deepEqual(JSON.parse(safeJsonLd(HOSTILE)), HOSTILE);
});

test("ordinary data is unchanged apart from escaping", () => {
  const plain = { "@type": "Dataset", name: "PURSUE corpus", count: 3 };
  assert.equal(safeJsonLd(plain), JSON.stringify(plain));
});
