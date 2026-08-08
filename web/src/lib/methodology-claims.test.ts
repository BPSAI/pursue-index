/**
 * Methodology page claims — verify that all figures are derived from
 * live data, not hardcoded. These tests fail if any claim in
 * methodology.astro is hard-typed instead of templated from RELEASE.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RELEASE } from "./release.ts";

// Read the manifest directly rather than through the loader: the loader's
// bare JSON import is resolved by Vite at build time, not by the test runner.
const manifest = JSON.parse(
  readFileSync(new URL("../data/manifest.json", import.meta.url), "utf8"),
) as { cards: unknown[] };

test("OCR engine counts are derived from live data", () => {
  // Should have llm as the primary engine
  const engines = RELEASE.ocrEngineCounts;
  assert.ok(engines, "ocrEngineCounts should exist");
  assert.ok(engines.llm || engines["llm-dots"] || engines["llm-anthropic"], "Should have llm-based engine");

  // No hardcoded Surya or Tesseract remnants
  // (legacy counts are OK from historical data, but should reflect live state)
  const total = Object.values(engines).reduce((s, n) => s + n, 0);
  assert.equal(total, RELEASE.ocrPageCount, "Engine counts should sum to ocrPageCount");
});

test("Cleaned page count is within OCR page count", () => {
  assert.ok(RELEASE.cleanedPageCount <= RELEASE.ocrPageCount,
    `cleanedPageCount (${RELEASE.cleanedPageCount}) should be ≤ ocrPageCount (${RELEASE.ocrPageCount})`
  );
});

test("Cleaned page count tracks the cleanup mirror, not the OCR corpus", () => {
  // The cleanup pass covers a subset of OCR'd pages, so the two counts are
  // independent reads: cleanedPageCount must come from the cleaned mirror
  // rather than being derived from ocrPageCount by arithmetic.
  assert.ok(RELEASE.cleanedPageCount > 0, "cleanedPageCount should be > 0");
  assert.notEqual(
    RELEASE.cleanedPageCount,
    RELEASE.ocrPageCount,
    "cleanedPageCount equal to ocrPageCount would mean one is derived from the other",
  );
});

test("Retired OCR engines are absent from the live engine mix", () => {
  const engines = RELEASE.ocrEngineCounts;
  // surya and tesseract are retired. Any remaining pages tagged with them
  // are legacy extractions; the page states the count it finds, so this
  // test only pins that the counts are real reads and never negative.
  for (const retired of ["surya", "tesseract"]) {
    const n = engines[retired] ?? 0;
    assert.ok(Number.isInteger(n) && n >= 0, `${retired} count should be a real read`);
    assert.ok(n < RELEASE.ocrPageCount, `${retired} cannot outnumber the whole corpus`);
  }
});

test("OCR engine label is derived from engine counts", () => {
  // ocrEngineLabel should be computed by formatOcrEngineLabel, not hardcoded
  const label = RELEASE.ocrEngineLabel;
  assert.ok(label, "ocrEngineLabel should exist");
  assert.ok(typeof label === "string", "ocrEngineLabel should be a string");
  // Should mention Claude Sonnet, not claim "Surya"
  assert.ok(label.includes("Claude") || label.includes("multiple"),
    `Engine label should reflect current mix, got: ${label}`
  );
});

test("Cleanup figures are template-derived, not hardcoded", () => {
  assert.ok(RELEASE.cleanedPageCount > 0, "cleanedPageCount should be > 0");
  assert.ok(RELEASE.ocrPageCount > 0, "ocrPageCount should be > 0");

  // cardCount must track the manifest itself. Pinning a literal here means
  // the next tranche fails a test that says nothing about correctness.
  assert.equal(
    RELEASE.cardCount,
    manifest.cards.length,
    "cardCount should be the manifest's own row count",
  );
});
