/**
 * Tests for the GalleryIsland's pure helpers. Run with ``node --test
 * src/components/gallery-helpers.test.ts``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { tileYear, withDisplayDates } from "./gallery-helpers.ts";

const card = (incident: string | null, release: string | null, display?: string | null) => ({
  incident_date: incident,
  release_date: release,
  display_date: display ?? null,
});

test("tileYear reads two-digit and four-digit numeric dates alike", () => {
  assert.equal(tileYear(card("5/24/62", "5/22/26")), "1962");
  assert.equal(tileYear(card("6/7/24", "5/8/26")), "2024");
  assert.equal(tileYear(card("6/7/2024", "5/8/2026")), "2024");
  assert.equal(tileYear(card(null, "5/8/2026")), "2026");
  assert.equal(tileYear(card(null, "5/8/26")), "2026");
});

test("tileYear keeps prose and range forms", () => {
  assert.equal(tileYear(card("Late 2025", "5/8/2026")), "2025");
  assert.equal(tileYear(card("1948-1950", "5/8/2026")), "1948");
});

test("tileYear does not read a year out of an implausible four-digit year", () => {
  // Previously "5/24/2962" yielded 2024 from its day-of-month.
  assert.equal(tileYear(card("5/24/2962", "5/22/2026")), "2026");
  assert.equal(tileYear(card("5/24/2962", null)), "—");
});

test("tileYear prefers a curated display_date", () => {
  assert.equal(tileYear(card("5/24/2962", "5/22/2026", "1962-05-24")), "1962");
  assert.equal(tileYear(card("6/7/2024", "5/8/2026", "2023")), "2023");
});

test("withDisplayDates attaches curated dates and skips abstentions", () => {
  const cards = [{ card_id: "a" }, { card_id: "b" }, { card_id: "c" }];
  const out = withDisplayDates(cards, [
    { card_id: "a", display_date: "1962-05-24" },
    { card_id: "b", display_date: null },
  ]);
  assert.equal(out[0].display_date, "1962-05-24");
  assert.equal("display_date" in out[1], false);
  assert.equal(out[2], cards[2]);
});
