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
  DIM_OPACITY,
  FULL_OPACITY,
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

test("pointToScatterplotRow encodes [x, y, category, opacityIndex] as a 4-tuple", () => {
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
  // Slot 3 is a SELECTOR INDEX (0 or 1) into the `opacity: [DIM, FULL]`
  // lookup table on the createScatterplot config — NOT a raw opacity
  // value. regl-scatterplot's shader does floor(state.w * multiplicator)
  // to index the opacity texture; with two-entry opacity array,
  // multiplicator = 1, so 0 → DIM_OPACITY and 1 → FULL_OPACITY.
  // Default = 1 (bright) so the bare `points.map(pointToScatterplotRow)`
  // initial-draw call site renders all-shown.
  assert.equal(row[3], 1);
  // Selector 0 → dim (non-matching during search).
  const dim = pointToScatterplotRow(p, 0);
  assert.equal(dim[3], 0);
  // Selector 1 → bright (matching, or no filter).
  const bright = pointToScatterplotRow(p, 1);
  assert.equal(bright[3], 1);
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

test("buildAtlasMiniSearch indexes title + text and supports prefix search", () => {
  // Atlas search relevance must match SearchIsland — both routes now source
  // their MiniSearch config from `buildSearchIndexOptions` (boost: title,
  // prefix, NO fuzzy) so the same query in the /atlas filter and the
  // /search input lights up the same rows. The shared factory replaces the
  // prior "must stay in lockstep" comment contract (vaivora P0 on PR #29).
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

test("buildAtlasMiniSearch inherits the no-fuzzy policy from the shared factory", () => {
  // Cross-surface guard: the same fuzzy-trap that motivated PR #29 on
  // /search must also be absent on /atlas. If a future edit re-adds
  // `fuzzy` to either path, this test (and its /search twin) fail loudly.
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "ft", page: 1, x: 0, y: 0, agency: "FBI" },
  ];
  const docs = new Map<string, { title: string; text: string }>([
    ["a-1", { title: "Yellow Area Anomaly", text: "yellow area report" }],
    // Edit-distance-1 of "yellow"/"area" — would match under fuzzy: 0.2.
    ["ft-1", { title: "Mellow Arena Notes", text: "mellow tune in arena" }],
  ]);
  const ms = buildAtlasMiniSearch(points, (p) => docs.get(`${p.card_id}-${p.page}`));
  const matched = searchIndicesViaMiniSearch(ms, "yellow area");
  assert.ok(matched.includes(0), "literal-match doc must be returned");
  assert.ok(
    !matched.includes(1),
    "fuzzy-only doc must NOT be returned (no-fuzzy policy is shared)",
  );
});

test("DIM_OPACITY and FULL_OPACITY are stable", () => {
  // The opacity[] lookup table baked into createScatterplot relies on
  // these specific values. Changing them changes the visual contract;
  // pinning here forces an intentional test-diff if a future PR alters them
  // (laverna P3 + nayru P2 on PR #31 — both reviewers independently flagged
  // that the prior tests asserted the slot-3 selector index but never the
  // literal opacity values, so a silent drift from 0.15 → 0.5 would slip
  // through CI).
  assert.equal(DIM_OPACITY, 0.15);
  assert.equal(FULL_OPACITY, 1.0);
});

test("pointToScatterplotRow opacityIndex param is type-narrowed to 0|1", () => {
  // vaivora P3 on PR #31: the `0 | 1` narrowing is the type-level guard
  // that prevents a future caller from passing a raw opacity value (e.g.
  // 0.15) into slot 3 — the exact bug class that `floor(0.15 * 1) === 0`
  // happened to mask before this PR. If this `@ts-expect-error` stops
  // erroring, the param type has been silently widened back to `number`
  // and the bug class has crept back in.
  // @ts-expect-error — 0.5 is not assignable to 0 | 1
  pointToScatterplotRow(
    { x: 0, y: 0, agency: "FBI", card_id: "abcd1234abcd1234", page: 1 },
    0.5,
  );
  // node --test strips TS at runtime so the call still executes; we only
  // care that the compiler flags it. tsc --noEmit (npm run build) is the
  // gate that actually enforces this — see pretest hook in package.json.
  assert.ok(true);
});

test("searchIndicesViaMiniSearch returns all indices for empty query", () => {
  // Empty query → "show everything" — the island uses this directly
  // to drive the search-redraw effect (no separate "no filter" branch).
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "b", page: 1, x: 1, y: 1, agency: "NASA" },
  ];
  const ms = buildAtlasMiniSearch(points, () => ({ title: "", text: "" }));
  assert.deepEqual(searchIndicesViaMiniSearch(ms, ""), [0, 1]);
  assert.deepEqual(searchIndicesViaMiniSearch(ms, "   "), [0, 1]);
});

