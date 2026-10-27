/**
 * The second-engine ASR cross-check (R7C.27) must state its own limit on
 * the methodology page: it catches a mishearing one engine makes and the
 * other doesn't, not an error both engines happen to share, and not an
 * error already present in the source audio. Grepping the rendered
 * source (the same pattern as methodology-no-novelty.test.ts) rather than
 * rendering the page, since the claim is static prose, not a templated
 * figure.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../pages/methodology.astro", import.meta.url), "utf8");

test("methodology page documents the second-engine ASR cross-check", () => {
  assert.match(source, /second[- ]engine/i);
  assert.match(source, /qc-coverage\.json/);
});

test("methodology page states the cross-check's limit: mishearings, not shared errors", () => {
  assert.match(source, /mishear/i);
  // The limit must be explicit: an error both engines share, or one
  // already in the source audio, is NOT caught by two-engine agreement.
  assert.match(source, /(both engines?|neither engine|same (mistake|error))/i);
});
