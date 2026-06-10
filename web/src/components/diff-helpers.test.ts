/**
 * Tests for the pure helper layer of the /diff page.
 *
 * Run with: `node --test src/components/diff-helpers.test.ts`
 * (the project's web-side test convention — see existing
 * `atlas-helpers.test.ts` for the same pattern).
 *
 * Splitting the data-shape logic out of DiffIsland keeps the island
 * thin and renders the diff algorithms unit-testable without spinning
 * up Preact / DOM.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseDiffParams,
  buildDiffParams,
  resolveAliases,
  diffWithAliases,
  fieldOnlyChanges,
  selectDefaultPair,
  normalizeSnapshotIndex,
} from "./diff-helpers.ts";
import type { AliasEntry, CardMetadata } from "../data/types.ts";

// --- parseDiffParams ---

test("parseDiffParams: empty search → both null", () => {
  assert.deepEqual(parseDiffParams(""), { from: null, to: null });
  assert.deepEqual(parseDiffParams("?"), { from: null, to: null });
});

test("parseDiffParams: both params present", () => {
  const out = parseDiffParams("?from=596cc188&to=c9cc83fcaf43");
  assert.equal(out.from, "596cc188");
  assert.equal(out.to, "c9cc83fcaf43");
});

test("parseDiffParams: only one param present", () => {
  assert.deepEqual(parseDiffParams("?to=c9cc83fc"), { from: null, to: "c9cc83fc" });
});

// --- buildDiffParams ---

test("buildDiffParams: round-trip", () => {
  const qs = buildDiffParams("596cc188", "c9cc83fcaf43");
  const parsed = parseDiffParams(`?${qs}`);
  assert.equal(parsed.from, "596cc188");
  assert.equal(parsed.to, "c9cc83fcaf43");
});

test("buildDiffParams: null-safe", () => {
  // When from/to is null we omit the key so the URL stays clean
  assert.equal(buildDiffParams(null, "c9cc83"), "to=c9cc83");
  assert.equal(buildDiffParams(null, null), "");
});

// --- selectDefaultPair ---

test("selectDefaultPair: empty index → both null", () => {
  assert.deepEqual(selectDefaultPair([]), { from: null, to: null });
});

test("selectDefaultPair: 1 entry → from = entry, to = null (we have nothing to compare against)", () => {
  const out = selectDefaultPair(["a.json"]);
  assert.equal(out.from, null);
  assert.equal(out.to, "a.json");
});

test("selectDefaultPair: 2+ entries → from = second-to-last, to = last", () => {
  const out = selectDefaultPair(["a.json", "b.json", "c.json"]);
  assert.equal(out.from, "b.json");
  assert.equal(out.to, "c.json");
});

// --- resolveAliases ---

test("resolveAliases: empty input → empty map", () => {
  assert.deepEqual(resolveAliases([]), {});
});

test("resolveAliases: single hop", () => {
  const aliases: AliasEntry[] = [
    { old_card_id: "aaa", new_card_id: "bbb", method: "byte_collision", established: "2026-05-01T00:00:00Z" },
  ];
  const m = resolveAliases(aliases);
  assert.deepEqual(m, { aaa: { terminal: "bbb", method: "byte_collision" } });
});

test("resolveAliases: multi-hop chain → terminal is the final id", () => {
  // aaa → bbb → ccc — walking the chain should produce {aaa: ccc, bbb: ccc}
  const aliases: AliasEntry[] = [
    { old_card_id: "aaa", new_card_id: "bbb", method: "byte_collision", established: "2026-05-01T00:00:00Z" },
    { old_card_id: "bbb", new_card_id: "ccc", method: "operator_manual", established: "2026-05-02T00:00:00Z" },
  ];
  const m = resolveAliases(aliases);
  assert.equal(m.aaa.terminal, "ccc");
  assert.equal(m.bbb.terminal, "ccc");
});

test("resolveAliases: operator_revoke removes the alias", () => {
  const aliases: AliasEntry[] = [
    { old_card_id: "aaa", new_card_id: "bbb", method: "operator_manual", established: "2026-05-01T00:00:00Z" },
    { old_card_id: "aaa", new_card_id: "bbb", method: "operator_revoke", established: "2026-05-03T00:00:00Z" },
  ];
  const m = resolveAliases(aliases);
  assert.deepEqual(m, {});
});

// --- diffWithAliases ---

function card(id: string, title: string, extras: Partial<CardMetadata> = {}): CardMetadata {
  return {
    card_id: id,
    title,
    asset_type: "PDF",
    agency: "FBI",
    release_date: null,
    incident_date: null,
    incident_location: null,
    redacted: false,
    description: null,
    asset_url: null,
    asset_filename: null,
    modal_image_url: null,
    dvids_video_id: null,
    video_title: null,
    pdf_pairing: null,
    video_pairing: null,
    image_alt_text: null,
    image_virin: null,
    original_classification: null,
    ...extras,
  };
}

test("diffWithAliases: empty inputs → empty result", () => {
  const out = diffWithAliases([], [], {});
  assert.deepEqual(out.added, []);
  assert.deepEqual(out.removed, []);
  assert.deepEqual(out.renamed, []);
});

test("diffWithAliases: simple add and remove (no aliases)", () => {
  const prev = [card("aaa", "A"), card("bbb", "B")];
  const curr = [card("aaa", "A"), card("ccc", "C")];
  const out = diffWithAliases(prev, curr, {});
  assert.equal(out.added.length, 1);
  assert.equal(out.added[0].card_id, "ccc");
  assert.equal(out.removed.length, 1);
  assert.equal(out.removed[0].card_id, "bbb");
  assert.equal(out.renamed.length, 0);
});

test("diffWithAliases: known rename collapses add+remove into renamed", () => {
  const prev = [card("aaa", "old name")];
  const curr = [card("bbb", "new name")];
  const aliases = { aaa: { terminal: "bbb", method: "byte_collision" } };
  const out = diffWithAliases(prev, curr, aliases);
  assert.equal(out.added.length, 0, "renamed card should not appear in added");
  assert.equal(out.removed.length, 0, "renamed card should not appear in removed");
  assert.equal(out.renamed.length, 1);
  assert.equal(out.renamed[0].from.card_id, "aaa");
  assert.equal(out.renamed[0].to.card_id, "bbb");
  assert.equal(out.renamed[0].method, "byte_collision");
});

test("diffWithAliases: alias whose terminal not in curr stays in removed", () => {
  // aaa renamed to bbb, but bbb isn't in curr either — alias is dangling.
  const prev = [card("aaa", "A")];
  const curr: CardMetadata[] = [];
  const aliases = { aaa: { terminal: "bbb", method: "operator_manual" } };
  const out = diffWithAliases(prev, curr, aliases);
  assert.equal(out.removed.length, 1);
  assert.equal(out.removed[0].card_id, "aaa");
  assert.equal(out.renamed.length, 0);
});

// --- fieldOnlyChanges ---

test("fieldOnlyChanges: same cards same fields → 0 changes", () => {
  const a = card("aaa", "title", { agency: "FBI", incident_date: "2023-10-24" });
  const b = card("aaa", "title", { agency: "FBI", incident_date: "2023-10-24" });
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
});

test("fieldOnlyChanges: title changed on same card_id → 1 change", () => {
  const a = card("aaa", "old title");
  const b = card("aaa", "new title");
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "aaa");
  assert.ok(out[0].fields.includes("title"));
});

test("fieldOnlyChanges: multiple fields changed → all listed", () => {
  const a = card("aaa", "T1", { agency: "FBI", incident_date: "2023-10-24" });
  const b = card("aaa", "T2", { agency: "DOW", incident_date: "2023-10-24" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("title"));
  assert.ok(out[0].fields.includes("agency"));
});

test("fieldOnlyChanges: ignores cards present in only one side (those are add/remove, not field-changes)", () => {
  const a = card("aaa", "A");
  const b = card("bbb", "B");
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
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
