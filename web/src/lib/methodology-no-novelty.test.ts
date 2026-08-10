/**
 * The novelty-detection surface (T48.2) is removed as ordinary product
 * evolution — the reference corpus was a static synthetic placeholder
 * for an abandoned design. This guards against novelty vocabulary
 * (the "Provenance / novelty detection" section, the research-preview
 * caveat bullet, the disclosure-status threshold table) drifting back
 * into the page. The chip UI / data plumbing that reads a novelty
 * payload if one is present is salvaged elsewhere and out of scope
 * here — this only covers the page's prose.
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
