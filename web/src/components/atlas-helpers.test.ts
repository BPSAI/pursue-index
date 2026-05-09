/**
 * Tests for the AtlasIsland's pure helper layer.
 *
 * The helpers are split from the island so the island stays small and
 * the data-shape logic (color mapping, k-means clustering for the
 * mobile fallback, query filtering) is testable without spinning up
 * regl-scatterplot. Run with ``node --test src/components/atlas-helpers.test.ts``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AGENCY_ORDER,
  agencyToCategory,
  categoryColors,
  filterIndicesByQuery,
  kmeansClusters,
  pointToScatterplotRow,
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

test("pointToScatterplotRow encodes [x, y, category, opacity]", () => {
  const p: AtlasPoint = {
    card_id: "abc",
    page: 3,
    x: 1.5,
    y: -2.0,
    agency: "FBI",
  };
  const row = pointToScatterplotRow(p);
  assert.equal(row[0], 1.5);
  assert.equal(row[1], -2.0);
  // Category index — 1 for FBI per AGENCY_ORDER.
  assert.equal(row[2], 1);
  // Default opacity slot — 1.0 for matched/all-shown, dim later via filter.
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

test("kmeansClusters partitions points into k clusters", () => {
  // Three obvious clusters; ask for 3 → expect 3 distinct labels and
  // every point assigned. Used by the <400px mobile fallback to group
  // dots into list-view buckets.
  const points: AtlasPoint[] = [
    { card_id: "a", page: 1, x: 0, y: 0, agency: "FBI" },
    { card_id: "a", page: 2, x: 0.1, y: 0.1, agency: "FBI" },
    { card_id: "b", page: 1, x: 10, y: 10, agency: "NASA" },
    { card_id: "b", page: 2, x: 10.1, y: 10.1, agency: "NASA" },
    { card_id: "c", page: 1, x: -10, y: -10, agency: "Department of War" },
    { card_id: "c", page: 2, x: -10.1, y: -9.9, agency: "Department of War" },
  ];
  const labels = kmeansClusters(points, 3, 42);
  assert.equal(labels.length, points.length);
  // Three distinct labels — the algorithm found three groups.
  const distinct = new Set(labels);
  assert.equal(distinct.size, 3);
  // Points with identical-ish coordinates land in the same cluster.
  assert.equal(labels[0], labels[1]);
  assert.equal(labels[2], labels[3]);
  assert.equal(labels[4], labels[5]);
});

test("kmeansClusters is deterministic under fixed seed", () => {
  const points: AtlasPoint[] = [];
  // 24 points across 4 clusters — small but enough that random init
  // would matter without seeding.
  const centres = [
    [0, 0],
    [10, 0],
    [0, 10],
    [10, 10],
  ];
  for (let c = 0; c < centres.length; c++) {
    for (let i = 0; i < 6; i++) {
      points.push({
        card_id: `c${c}`,
        page: i,
        x: centres[c][0] + (i % 2) * 0.1,
        y: centres[c][1] + (i % 3) * 0.1,
        agency: "FBI",
      });
    }
  }
  const a = kmeansClusters(points, 4, 42);
  const b = kmeansClusters(points, 4, 42);
  assert.deepEqual(a, b);
});
