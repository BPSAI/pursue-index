/**
 * Tests for the report-rendering layer of the /diff page's pure helper
 * module: readable field labels, snapshot-index normalization, sha/time
 * formatters, promoted-state resolution, and the grouped snapshot-option
 * builder the selector UI renders from.
 *
 * Run with: `node --test src/components/diff-helpers-report.test.ts`
 * (the project's web-side test convention — see existing
 * `atlas-helpers.test.ts` for the same pattern).
 *
 * Split out of `diff-helpers.test.ts` (T48.10) along its existing
 * `// --- section ---` seams — see the sibling `diff-helpers-pairing.test.ts`
 * and `diff-helpers-field-changes.test.ts` for the rest of that file's
 * coverage.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  normalizeSnapshotIndex,
  shaPrefix,
  formatSnapshotTimestamp,
  findPromotedFromFilename,
  buildGroupedSnapshotOptions,
  formatUpstreamSnapshotLabel,
  formatPromotedStateLabel,
  DIFF_SKIP_FIELDS,
  LOCAL_CURATION_FIELDS,
  FIELD_LABELS,
  formatFieldLabel,
} from "./diff-helpers.ts";

// --- formatFieldLabel ---

test("formatFieldLabel: every field the real manifest can surface has a readable label", () => {
  // Pinned against the key union of the published manifest, NOT the
  // hand-written `card()` helper this used to iterate. The helper is a
  // copy of the fields someone remembered, so it agreed with FIELD_LABELS
  // by construction and could never report a gap; `fieldOnlyChanges`
  // enumerates the keys of the fetched JSON, so only the real payload
  // says which fields the page can actually render.
  const manifest = JSON.parse(
    readFileSync(new URL("../../../data/manifests/latest.json", import.meta.url), "utf-8"),
  ) as { cards: Array<Record<string, unknown>> };
  assert.ok(manifest.cards.length > 0, "manifest must be non-empty for this pin to mean anything");
  const keys = new Set<string>();
  for (const row of manifest.cards) for (const k of Object.keys(row)) keys.add(k);
  const unlabeled = [...keys].filter(
    (f) =>
      !DIFF_SKIP_FIELDS.has(f) &&
      !LOCAL_CURATION_FIELDS.has(f) &&
      !Object.prototype.hasOwnProperty.call(FIELD_LABELS, f),
  );
  assert.deepEqual(
    unlabeled.sort(),
    [],
    "manifest fields with no FIELD_LABELS entry — label them, or exclude them deliberately",
  );
});

test("formatFieldLabel: previously-never-displayed fields render readably, not as raw snake_case", () => {
  assert.equal(formatFieldLabel("pdf_pairing"), "PDF pairing");
  assert.equal(formatFieldLabel("video_pairing"), "Video pairing");
  assert.equal(formatFieldLabel("dvids_video_id"), "DVIDS video ID");
});

test("formatFieldLabel: unknown field falls back to the raw key rather than throwing", () => {
  assert.equal(formatFieldLabel("some_future_column"), "some_future_column");
});

// --- normalizeSnapshotIndex ---
// The web snapshot index historically shipped as a bare filename list
// (string[]); the enriched form carries per-snapshot label metadata so
// the /diff selectors don't render "?? cards" until a snapshot is
// lazily fetched. normalizeSnapshotIndex tolerates BOTH so a deploy
// straddling the format change never breaks the page.

test("normalizeSnapshotIndex: legacy string[] → filenames, empty meta", () => {
  const out = normalizeSnapshotIndex(["a.json", "b.json"]);
  assert.deepEqual(out.filenames, ["a.json", "b.json"]);
  assert.deepEqual(out.meta, {});
});

test("normalizeSnapshotIndex: enriched objects → filenames + per-file meta", () => {
  const out = normalizeSnapshotIndex([
    { filename: "a.json", fetched_at: "2026-05-27T13:48:27Z", card_count: 222 },
    { filename: "b.json", fetched_at: "2026-06-10T16:17:15Z", card_count: 222 },
  ]);
  assert.deepEqual(out.filenames, ["a.json", "b.json"]);
  assert.equal(out.meta["a.json"].fetched_at, "2026-05-27T13:48:27Z");
  assert.equal(out.meta["a.json"].card_count, 222);
  assert.equal(out.meta["b.json"].fetched_at, "2026-06-10T16:17:15Z");
});

test("normalizeSnapshotIndex: object missing optional fields → filename kept, meta fields undefined", () => {
  const out = normalizeSnapshotIndex([{ filename: "a.json" }]);
  assert.deepEqual(out.filenames, ["a.json"]);
  assert.equal(out.meta["a.json"].fetched_at, undefined);
  assert.equal(out.meta["a.json"].card_count, undefined);
});

test("normalizeSnapshotIndex: null / non-array → empty result (defensive)", () => {
  assert.deepEqual(normalizeSnapshotIndex(null), { filenames: [], meta: {} });
  assert.deepEqual(normalizeSnapshotIndex(undefined), { filenames: [], meta: {} });
  assert.deepEqual(normalizeSnapshotIndex({}), { filenames: [], meta: {} });
});

test("normalizeSnapshotIndex: drops entries with no usable filename", () => {
  const out = normalizeSnapshotIndex(["a.json", { fetched_at: "x" }, { filename: "" }, 42]);
  assert.deepEqual(out.filenames, ["a.json"]);
});

// --- shaPrefix / formatSnapshotTimestamp ------------------------------

test("shaPrefix: strips .json and truncates to 8 chars", () => {
  assert.equal(shaPrefix("5216a20bc3419802ebbcc6716e0deede3e873bafbbe273e3a0e4e31f1acd0125.json"), "5216a20b");
});

test("formatSnapshotTimestamp: includes minute-precision time, not just date", () => {
  assert.equal(formatSnapshotTimestamp("2026-06-12T12:07:04.089105Z"), "2026-06-12 12:07Z");
});

test("formatSnapshotTimestamp: distinguishes the two 2026-06-12 double-drop snapshots", () => {
  const a = formatSnapshotTimestamp("2026-06-12T12:07:04.089105Z");
  const b = formatSnapshotTimestamp("2026-06-12T15:04:42.063222Z");
  assert.notEqual(a, b);
});

test("formatSnapshotTimestamp: undefined → em dash placeholder", () => {
  assert.equal(formatSnapshotTimestamp(undefined), "—");
});

// --- findPromotedFromFilename ------------------------------------------
// Filenames are `${csv_sha256}.json` (poll_snapshot.py) — matching on that
// exact identity means the promoted-state label never guesses from date or
// card count, both of which can collide with an unrelated snapshot (the
// war.gov double-drop on 2026-06-12).

test("findPromotedFromFilename: matches the snapshot whose filename is current's csv_sha256", () => {
  const index = ["aaa.json", "bbb222.json"];
  assert.equal(findPromotedFromFilename(index, "bbb222"), "bbb222.json");
});

test("findPromotedFromFilename: no matching snapshot → null", () => {
  assert.equal(findPromotedFromFilename(["aaa.json"], "zzz"), null);
});

test("findPromotedFromFilename: current has no csv_sha256 → null", () => {
  assert.equal(findPromotedFromFilename(["aaa.json"], undefined), null);
});

// --- buildGroupedSnapshotOptions / label formatters ---------------------
// The option list must never conflate upstream (war.gov) snapshots with our
// promoted state the way the old flat `[...index, @current]` array did.

test("buildGroupedSnapshotOptions: one upstream entry per index filename", () => {
  const index = ["a.json", "b.json"];
  const meta = {
    "a.json": { fetched_at: "2026-05-01T00:00:00Z", card_count: 10 },
    "b.json": { fetched_at: "2026-05-02T00:00:00Z", card_count: 12 },
  };
  const grouped = buildGroupedSnapshotOptions(
    index,
    meta,
    { fetched_at: "2026-05-03T00:00:00Z", card_count: 12, csv_sha256: "b" },
    "@current",
  );
  assert.equal(grouped.upstream.length, 2);
  assert.deepEqual(grouped.upstream.map((o) => o.filename), ["a.json", "b.json"]);
});

test("buildGroupedSnapshotOptions: exactly one promoted entry, never merged into upstream", () => {
  const grouped = buildGroupedSnapshotOptions(
    ["a.json"],
    { "a.json": { fetched_at: "2026-05-01T00:00:00Z", card_count: 10 } },
    { fetched_at: "2026-05-02T00:00:00Z", card_count: 10, csv_sha256: "a" },
    "@current",
  );
  assert.equal(grouped.promoted.filename, "@current");
  assert.ok(!grouped.upstream.some((o) => o.filename === "@current"));
});

test("buildGroupedSnapshotOptions: promoted entry names the snapshot it was promoted from", () => {
  const grouped = buildGroupedSnapshotOptions(
    ["aaa.json", "bbb.json"],
    {
      "aaa.json": { fetched_at: "2026-05-01T00:00:00Z", card_count: 10 },
      "bbb.json": { fetched_at: "2026-05-02T00:00:00Z", card_count: 12 },
    },
    { fetched_at: "2026-05-03T00:00:00Z", card_count: 12, csv_sha256: "bbb" },
    "@current",
  );
  assert.equal(grouped.promoted.promotedFrom, "bbb.json");
});

test("buildGroupedSnapshotOptions: unresolved promotion → promotedFrom null (never fabricated)", () => {
  const grouped = buildGroupedSnapshotOptions(
    ["aaa.json"],
    { "aaa.json": { fetched_at: "2026-05-01T00:00:00Z", card_count: 10 } },
    { fetched_at: "2026-05-03T00:00:00Z", card_count: 999, csv_sha256: "unmatched" },
    "@current",
  );
  assert.equal(grouped.promoted.promotedFrom, null);
});

test("formatUpstreamSnapshotLabel: sha8 · date time · N cards", () => {
  const label = formatUpstreamSnapshotLabel({
    filename: "5216a20bc3419802ebbcc6716e0deede3e873bafbbe273e3a0e4e31f1acd0125.json",
    fetched_at: "2026-06-12T12:07:04.089105Z",
    card_count: 294,
  });
  assert.equal(label, "5216a20b · 2026-06-12 12:07Z · 294 cards");
});

test("formatPromotedStateLabel: names the promotion source, no standalone date", () => {
  const label = formatPromotedStateLabel({
    filename: "@current",
    fetched_at: "2026-08-07T11:46:47.222422Z",
    card_count: 375,
    promotedFrom: "5f5698f132245115dd9d4a5197d2748847f281e466d8b660de036aa3c4b678c7.json",
  });
  assert.equal(label, "PROMOTED STATE · from 5f5698f1 · 375 cards");
  // The bug this fixes: CURRENT carrying its own date reads as a second
  // war.gov drop. The promoted-state label must never carry one.
  assert.ok(!label.includes("2026-08-07"));
});

test("formatPromotedStateLabel: unresolved promotion still never fabricates a date", () => {
  const label = formatPromotedStateLabel({
    filename: "@current",
    fetched_at: "2026-08-07T11:46:47.222422Z",
    card_count: 375,
    promotedFrom: null,
  });
  assert.ok(!label.includes("2026-08-07"));
  assert.match(label, /unresolved/);
});

// --- AC pin: real data/manifests/snapshots/index.json -------------------

test("buildGroupedSnapshotOptions: real index.json → exactly one upstream entry per file, plus one promoted entry", () => {
  const raw = JSON.parse(
    readFileSync(new URL("../../../data/manifests/snapshots/index.json", import.meta.url), "utf-8"),
  ) as { snapshots: Array<{ filename: string; fetched_at: string; card_count: number }> };
  assert.ok(raw.snapshots.length > 0, "fixture must actually contain snapshots");

  const { filenames, meta } = normalizeSnapshotIndex(raw.snapshots);
  assert.equal(filenames.length, raw.snapshots.length);

  const grouped = buildGroupedSnapshotOptions(
    filenames,
    meta,
    { fetched_at: "2026-08-07T11:46:47.222422Z", card_count: 375, csv_sha256: "unused-for-this-pin" },
    "@current",
  );
  assert.equal(grouped.upstream.length, raw.snapshots.length);
  assert.deepEqual(
    grouped.upstream.map((o) => o.filename),
    raw.snapshots.map((s) => s.filename),
  );
  assert.ok(!grouped.upstream.some((o) => o.filename === "@current"));
  assert.equal(grouped.promoted.filename, "@current");
});
