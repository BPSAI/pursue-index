/**
 * Build-time inputs for /methodology.
 *
 * Every figure on that page is derived from the data in this repo at build
 * time. These helpers are what derive them, so they are tested against the
 * real files — and against a missing file, where they must throw rather
 * than substitute a frozen literal: this is a static build, so a
 * substituted number would ship as a claim about the corpus that nothing
 * produced.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  cleanupCoverage,
  describeRetiredEngines,
  describeSuryaMigration,
  describeSuryaMigrationBrief,
  readCleanupStats,
  readOcrCardIds,
  readSidecarModelBreakdown,
} from "./methodology-data.ts";

const PAGES_CLEANED = new URL("../../public/data/pages-cleaned.json", import.meta.url).pathname;
const PAGES = new URL("../../public/data/pages.json", import.meta.url).pathname;
const SIDECARS = new URL("../data/image-observations", import.meta.url).pathname;

// --- readCleanupStats -------------------------------------------------

test("readCleanupStats: totals and skip causes are derived from pages-cleaned.json", () => {
  const raw = JSON.parse(readFileSync(PAGES_CLEANED, "utf8")) as {
    pages: Array<{ card_id?: string; text?: string; cleanup_skipped?: string }>;
  };
  const stats = readCleanupStats([PAGES_CLEANED]);

  assert.equal(stats.totalPagesInCleanupPass, raw.pages.length);
  assert.equal(
    stats.totalCleanedPages,
    raw.pages.filter((p) => typeof p.text === "string" && p.text.length > 0).length,
  );
  assert.equal(
    stats.cardsInCleanupPass,
    new Set(raw.pages.map((p) => p.card_id).filter(Boolean)).size,
  );
  assert.equal(stats.skippedPages, stats.totalPagesInCleanupPass - stats.totalCleanedPages);
});

test("readCleanupStats: cards looked at and cards cleaned are counted separately", () => {
  // A card can enter the pass and leave with every page skipped. Counting
  // those as "cleaned" overstates coverage, which is what the page used to do.
  const raw = JSON.parse(readFileSync(PAGES_CLEANED, "utf8")) as {
    pages: Array<{ card_id?: string; text?: string }>;
  };
  const stats = readCleanupStats([PAGES_CLEANED]);
  assert.equal(
    stats.cardsWithCleanedText,
    new Set(
      raw.pages
        .filter((p) => p.card_id && typeof p.text === "string" && p.text.length > 0)
        .map((p) => p.card_id),
    ).size,
  );
  assert.ok(
    stats.cardsWithCleanedText <= stats.cardsInCleanupPass,
    "a card cannot be cleaned without entering the pass",
  );
  assert.deepEqual(
    [...stats.cardIds].sort(),
    [...new Set(raw.pages.map((p) => p.card_id).filter(Boolean))].sort(),
    "cardIds must be the population the counts are taken from",
  );
});

test("readCleanupStats: every skipped page is attributed to a cause", () => {
  const stats = readCleanupStats([PAGES_CLEANED]);
  const summed = stats.skipCauses.reduce((n, c) => n + c.count, 0);
  assert.equal(summed, stats.skippedPages);
  assert.deepEqual(
    stats.skipCauses.map((c) => c.cause).sort(),
    ["content_filter", "empty_input", "length_divergence"],
  );
  // Ordered largest-first so the page reads worst-cause-first.
  for (let i = 1; i < stats.skipCauses.length; i++) {
    assert.ok(stats.skipCauses[i - 1].count >= stats.skipCauses[i].count);
  }
});

test("readCleanupStats: skipped pages are not all one cause", () => {
  // The page used to attribute every skip to empty source OCR. Pin that the
  // data disagrees, so the single-cause sentence cannot come back unnoticed.
  const stats = readCleanupStats([PAGES_CLEANED]);
  const nonEmpty = stats.skipCauses.filter((c) => c.cause !== "empty_input");
  assert.ok(nonEmpty.some((c) => c.count > 0), "skips have more than one cause");
});

test("readCleanupStats: unreadable input throws (a static build must fail, not guess)", () => {
  assert.throws(() => readCleanupStats(["/nonexistent/pages-cleaned.json"]), /pages-cleaned/);
});

// --- readSidecarModelBreakdown ---------------------------------------

test("readSidecarModelBreakdown: total equals the summed model split", () => {
  const b = readSidecarModelBreakdown([SIDECARS]);
  const summed = Object.values(b.modelCounts).reduce((n, c) => n + c, 0);
  assert.equal(b.total, summed, "the sidecar total must equal the model split it reports");
  assert.ok(b.total > 0);
});

test("readSidecarModelBreakdown: files without an our_pass model are not sidecars", () => {
  // The directory carries an index.json alongside the sidecars; counting it
  // made the total one higher than the split it sat next to.
  const b = readSidecarModelBreakdown([SIDECARS]);
  assert.ok(!Object.keys(b.modelCounts).includes("undefined"));
  assert.equal(b.total, Object.values(b.modelCounts).reduce((n, c) => n + c, 0));
});

test("readSidecarModelBreakdown: unreadable directory throws", () => {
  assert.throws(() => readSidecarModelBreakdown(["/nonexistent/image-observations"]), /sidecar/i);
});

// --- readOcrCardIds ---------------------------------------------------

test("readOcrCardIds: the distinct cards carrying OCR text", () => {
  const rows = JSON.parse(readFileSync(PAGES, "utf8")) as Array<{
    card_id?: string;
    text?: string;
  }>;
  const expected = new Set(
    rows.filter((r) => typeof r.text === "string" && r.text.length > 0).map((r) => r.card_id),
  );
  assert.deepEqual([...readOcrCardIds([PAGES])].sort(), [...expected].sort());
});

test("readOcrCardIds: unreadable input throws", () => {
  assert.throws(() => readOcrCardIds(["/nonexistent/pages.json"]), /pages\.json/);
});

// --- cleanupCoverage --------------------------------------------------

test("cleanupCoverage: coverage is the intersection, not the smaller count", () => {
  // The two populations are read from different files and neither contains
  // the other: a card can be in the cleanup pass with no OCR text at all.
  const cov = cleanupCoverage(["a", "b", "x"], new Set(["a", "b", "c", "d"]));
  assert.equal(cov.covered, 2);
  assert.equal(cov.cleanupCards, 3);
  assert.equal(cov.ocrCards, 4);
  assert.equal(cov.outsideOcr, 1, "the card with no OCR text is not covered by anything");
});

test("cleanupCoverage: the rendered pair is subset-consistent by construction", () => {
  // "{covered} of {ocrCards}" is only a true sentence if covered can never
  // exceed ocrCards — which it cannot, being an intersection with that set.
  const stats = readCleanupStats([PAGES_CLEANED]);
  const cov = cleanupCoverage(stats.cardIds, readOcrCardIds([PAGES]));
  assert.ok(cov.covered <= cov.ocrCards, `${cov.covered} of ${cov.ocrCards} is not a subset`);
  assert.ok(cov.covered <= cov.cleanupCards);
  assert.equal(cov.outsideOcr, cov.cleanupCards - cov.covered);
  assert.ok(cov.covered > 0, "the page states a real coverage figure");
});

// --- describeSuryaMigration ------------------------------------------

test("describeSuryaMigration: zero surya pages reads as complete, with no pending tail", () => {
  const s = describeSuryaMigration(0);
  assert.match(s, /complete/i);
  assert.ok(!/tail/i.test(s), `must not promise a pending tail: ${s}`);
  assert.match(s, /no .*surya/i);
});

test("describeSuryaMigration: remaining surya pages are stated with their count", () => {
  const s = describeSuryaMigration(1234);
  assert.match(s, /1,234/);
  assert.ok(!/complete/i.test(s), `must not claim completion while pages remain: ${s}`);
});

// --- describeSuryaMigrationBrief -------------------------------------

test("describeSuryaMigrationBrief: says the same thing as the long form, in its own words", () => {
  // The page states the migration's position twice, in two sections. Rendered
  // from one count, phrased differently, so the two can never disagree and a
  // reader does not meet the identical paragraph twice.
  for (const pages of [0, 1234]) {
    const brief = describeSuryaMigrationBrief(pages);
    assert.notEqual(brief, describeSuryaMigration(pages));
    assert.ok(brief.length < describeSuryaMigration(pages).length);
  }
  assert.match(describeSuryaMigrationBrief(0), /no .*surya/i);
  assert.match(describeSuryaMigrationBrief(1234), /1,234/);
});

// --- describeRetiredEngines ------------------------------------------

test("describeRetiredEngines: an empty count is stated, not called legacy data", () => {
  // The engine table used to footnote surya/tesseract as "legacy Release-01
  // page data only" while the same page said no surya-tagged pages remain.
  const note = describeRetiredEngines({ llm: 8233, dots: 406 });
  assert.match(note, /retired/i);
  assert.ok(!/legacy/i.test(note), `nothing legacy remains to point at: ${note}`);
});

test("describeRetiredEngines: pages still tagged with a retired engine are counted", () => {
  const note = describeRetiredEngines({ llm: 10, surya: 1234, tesseract: 7 });
  assert.match(note, /1,234/);
  assert.match(note, /7/);
  assert.match(note, /legacy/i);
});
