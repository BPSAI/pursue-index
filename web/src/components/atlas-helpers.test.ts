/**
 * Tests for the AtlasIsland's pure helper layer.
 *
 * The helpers are split from the island so the island stays small and
 * the data-shape logic (color mapping, query filtering) is testable
 * without spinning up regl-scatterplot. Run with ``node --test
 * src/components/atlas-helpers.test.ts``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AGENCY_ORDER,
  agencyToCategory,
  buildAtlasMiniSearch,
  buildCardHref,
  categoryColors,
  filterIndicesByQuery,
  pointToScatterplotRow,
  searchIndicesViaMiniSearch,
} from "./atlas-helpers.ts";
import type { AtlasPoint } from "./atlas-helpers.ts";

test("AGENCY_ORDER is the canonical agency ordering", () => {
  // Stable ordering matters: the regl-scatterplot category index is the
  // index into this array, so reordering it would silently re-color
  // every point in deployed builds.
  assert.deepEqual(AGENCY_ORDER, [
    "Department of War",
    "FBI",
    "NASA",
    "Department of State",
  ]);
});

test("agencyToCategory maps known agencies to their stable index", () => {
  assert.equal(agencyToCategory("Department of War"), 0);
  assert.equal(agencyToCategory("FBI"), 1);
  assert.equal(agencyToCategory("NASA"), 2);
  assert.equal(agencyToCategory("Department of State"), 3);
});

test("agencyToCategory returns the unknown bucket for missing agencies", () => {
  // Unknowns land at AGENCY_ORDER.length so the color palette can pad
  // a neutral entry at that index.
  assert.equal(agencyToCategory("UNKNOWN"), 4);
  assert.equal(agencyToCategory(""), 4);
  assert.equal(agencyToCategory("Some Mystery Agency"), 4);
});

test("categoryColors has one entry per category index, including unknown", () => {
  const colors = categoryColors();
  assert.equal(colors.length, AGENCY_ORDER.length + 1);
  for (const c of colors) {
    // RGB triplet in 0..1 range, plus alpha — the regl-scatterplot
    // expected float color shape.
    assert.equal(c.length, 4);
    for (const channel of c) {
      assert.ok(channel >= 0 && channel <= 1, `channel out of [0,1]: ${channel}`);
    }
  }
});

test("pointToScatterplotRow encodes [x, y, category, opacity] as a 4-tuple", () => {
  const p: AtlasPoint = {
    card_id: "abc",
    page: 3,
    x: 1.5,
    y: -2.0,
    agency: "FBI",
  };
  const row = pointToScatterplotRow(p);
  // Length lock: regl-scatterplot's `colorBy: "valueA"` and
  // `opacityBy: "valueB"` reach into slots 2 and 3 respectively. If
  // this row ever shrinks, all dots silently lose their color/dim
  // encoding (the original /atlas color-and-search bug). Lock the
  // tuple length here so a future schema tweak surfaces loudly.
  assert.equal(row.length, 4);
  assert.equal(row[0], 1.5);
  assert.equal(row[1], -2.0);
  // Category index — 1 for FBI per AGENCY_ORDER. Consumed via
  // `colorBy: "valueA"` on the createScatterplot config.
  assert.equal(row[2], 1);
  // Default opacity slot — 1.0 for matched/all-shown, dim later via
  // a draw() re-upload when search runs. Consumed via
  // `opacityBy: "valueB"`.
  assert.equal(row[3], 1.0);
});

test("filterIndicesByQuery returns all indices when query is empty", () => {
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "b", page: 1, x: 1, y: 1, agency: "NASA" },
  ];
  // Empty query → all indices match. Caller treats that as "show all".
  assert.deepEqual(filterIndicesByQuery(points, "", () => "anything"), [0, 1]);
  assert.deepEqual(filterIndicesByQuery(points, "   ", () => "anything"), [0, 1]);
});

test("filterIndicesByQuery selects indices whose page text matches", () => {
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "a", page: 2, x: 0, y: 0, agency: "FBI" },
    { card_id: "b", page: 1, x: 0, y: 0, agency: "NASA" },
  ];
  const corpus: Record<string, string> = {
    "a-1": "Project Blue Book",
    "a-2": "completely unrelated",
    "b-1": "another mention of Blue Book",
  };
  const lookup = (p: AtlasPoint) => corpus[`${p.card_id}-${p.page}`] ?? "";
  // Case-insensitive whole-string contains is enough for the live
  // dim-non-matchers UX; if we ever want stemmed matches, swap in
  // MiniSearch under the same callback.
  assert.deepEqual(
    filterIndicesByQuery(points, "blue book", lookup),
    [0, 2],
  );
});

test("buildCardHref emits hash-only URL with no ?page= squat", () => {
  // The site-wide deep-link contract reserves the query slot for ?q=…
  // (Cite.astro / SearchIsland use it for highlight carry-through). Atlas
  // links must NOT add ?page=N — that field is unread, conflicts with ?q=,
  // and bloats shared URLs. The fragment alone (#page-N) is what
  // CardOcrIsland / CardReaderView consume.
  const href = buildCardHref("/base", "abc123def456abcd", 7);
  assert.equal(href, "/base/card/abc123def456abcd#page-7");
  assert.ok(!href.includes("?"), "no query slot squat");
  assert.ok(!href.includes("?page="), "must not emit ?page=N");
});

test("buildCardHref encodes the card_id defensively", () => {
  // Card IDs are sha256[:16] hex by spec, so encoding is a no-op today.
  // We still encode to harden against any future flow that surfaces a
  // user-supplied or non-hex token through the same helper (laverna
  // SEC-003 — cheap insurance).
  const dirty = "weird/value with spaces&page=999";
  const href = buildCardHref("/b", dirty, 1);
  // The whole card_id segment is encoded as a single path component.
  assert.equal(
    href,
    `/b/card/${encodeURIComponent(dirty)}#page-1`,
  );
  // No raw `?` from the dirty input leaks through into the URL.
  assert.ok(!href.includes("?"));
});

test("buildAtlasMiniSearch indexes title + text and supports stemmed search", () => {
  // Atlas search relevance must match SearchIsland — same MiniSearch
  // configuration (boost: title, prefix, fuzzy) so the same query in the
  // /atlas filter and the /search input lights up the same rows.
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "a", page: 2, x: 0, y: 0, agency: "FBI" },
    { card_id: "b", page: 1, x: 0, y: 0, agency: "NASA" },
  ];
  const docs = new Map<string, { title: string; text: string }>([
    ["a-1", { title: "Project Blue Book", text: "1947 sighting" }],
    ["a-2", { title: "Roswell incident", text: "balloons or otherwise" }],
    ["b-1", { title: "Apollo telemetry", text: "blue book references" }],
  ]);
  const ms = buildAtlasMiniSearch(points, (p) => docs.get(`${p.card_id}-${p.page}`));
  // "blue" should hit both the title-boosted Project Blue Book and the
  // body-text reference in b-1, but not the unrelated Roswell/Apollo
  // entries (the latter has the raw stem only via prefix on "blue").
  const matched = searchIndicesViaMiniSearch(ms, "blue");
  // Order isn't guaranteed; presence + count is.
  assert.ok(matched.includes(0), "Project Blue Book must match");
  assert.ok(matched.includes(2), "body-text mention must match");
  assert.ok(!matched.includes(1), "unrelated Roswell entry must not match");
});

test("searchIndicesViaMiniSearch returns all indices for empty query", () => {
  // Empty query → "show everything" — same convention as
  // filterIndicesByQuery so the island can drop the helper in directly.
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "b", page: 1, x: 1, y: 1, agency: "NASA" },
  ];
  const ms = buildAtlasMiniSearch(points, () => ({ title: "", text: "" }));
  assert.deepEqual(searchIndicesViaMiniSearch(ms, ""), [0, 1]);
  assert.deepEqual(searchIndicesViaMiniSearch(ms, "   "), [0, 1]);
});

