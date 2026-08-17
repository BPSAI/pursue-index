/**
 * The novelty-detection surface is removed as ordinary product evolution —
 * the reference corpus was a static synthetic placeholder for a design that
 * was not carried forward. This guards against novelty vocabulary (the
 * "Provenance / novelty detection" section, the research-preview caveat
 * bullet, the disclosure-status threshold table) drifting back into the
 * methodology page, which is the only thing this file covers; the components
 * that presented the comparison are gone, and their absence is guarded on the
 * Python side.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../pages/methodology.astro", import.meta.url), "utf8");

test("methodology page contains no novelty-detection vocabulary", () => {
  assert.doesNotMatch(source, /novelty/i);
  assert.doesNotMatch(source, /disclosure.status/i);
  assert.doesNotMatch(source, /black vault/i);
});
