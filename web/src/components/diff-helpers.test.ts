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
import { readFileSync } from "node:fs";
import {
  parseDiffParams,
  buildDiffParams,
  resolveAliases,
  diffWithAliases,
  fieldOnlyChanges,
  pairRowsByCardId,
  unpairedRowEntries,
  selectDefaultPair,
  selectDefaultPairWithCurrent,
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

// --- selectDefaultPairWithCurrent (recency-aware default) ---

const SENT = "@current";

test("selectDefaultPairWithCurrent: empty index → compare against @current", () => {
  assert.deepEqual(
    selectDefaultPairWithCurrent([], {}, "2026-06-12T00:00:00Z", SENT),
    { from: null, to: SENT },
  );
});

test("selectDefaultPairWithCurrent: @current newer than newest snapshot → (newest, @current)", () => {
  const index = ["a.json", "b.json"];
  const meta = { "b.json": { fetched_at: "2026-05-27T00:00:00Z" } };
  // latest.json scraped AFTER the newest snapshot (normal pre-ingest scrape).
  const out = selectDefaultPairWithCurrent(index, meta, "2026-06-01T00:00:00Z", SENT);
  assert.deepEqual(out, { from: "b.json", to: SENT });
});

test("selectDefaultPairWithCurrent: pending tranche (newest snapshot NEWER than @current) → two newest snapshots", () => {
  // The Release-3 regression: the detected snapshot is newer than latest.json
  // (not yet ingested). Must read old→new (additions), NOT snapshot→@current.
  const index = ["6be2.json", "5216.json"]; // chronological oldest→newest
  const meta = {
    "6be2.json": { fetched_at: "2026-05-27T13:48:27Z", card_count: 222 },
    "5216.json": { fetched_at: "2026-06-12T12:07:04Z", card_count: 294 },
  };
  // latest.json is still the 6be2 state (May 27) — behind the new snapshot.
  const out = selectDefaultPairWithCurrent(index, meta, "2026-05-27T13:48:27Z", SENT);
  assert.deepEqual(out, { from: "6be2.json", to: "5216.json" });
});

test("selectDefaultPairWithCurrent: post-promotion (@current == newest snapshot fetched_at) → two newest snapshots", () => {
  const index = ["6be2.json", "5216.json"];
  const meta = {
    "6be2.json": { fetched_at: "2026-05-27T13:48:27Z" },
    "5216.json": { fetched_at: "2026-06-12T12:07:04Z" },
  };
  // After ingest, latest.json == newest snapshot (equal fetched_at, not newer).
  const out = selectDefaultPairWithCurrent(index, meta, "2026-06-12T12:07:04Z", SENT);
  assert.deepEqual(out, { from: "6be2.json", to: "5216.json" });
});

test("selectDefaultPairWithCurrent: missing newest meta + a current ts → falls back to (newest, @current)", () => {
  // No fetched_at known for the newest snapshot: prefer the dated @current.
  const out = selectDefaultPairWithCurrent(["a.json", "b.json"], {}, "2026-06-12T00:00:00Z", SENT);
  assert.deepEqual(out, { from: "b.json", to: SENT });
});

test("selectDefaultPairWithCurrent: no current fetched_at → two newest snapshots", () => {
  const index = ["a.json", "b.json"];
  const meta = { "b.json": { fetched_at: "2026-05-27T00:00:00Z" } };
  const out = selectDefaultPairWithCurrent(index, meta, undefined, SENT);
  assert.deepEqual(out, { from: "a.json", to: "b.json" });
});

// --- single-snapshot histories: never return a null `from` (DiffIsland would
//     hang in the loading state). Codex P2 / PR #88. ---

test("selectDefaultPairWithCurrent: single snapshot, @current newer → (snapshot, @current)", () => {
  const meta = { "s.json": { fetched_at: "2026-05-27T00:00:00Z" } };
  const out = selectDefaultPairWithCurrent(["s.json"], meta, "2026-06-01T00:00:00Z", SENT);
  assert.deepEqual(out, { from: "s.json", to: SENT });
});

test("selectDefaultPairWithCurrent: single snapshot pending (snapshot newer than @current) → (@current, snapshot)", () => {
  // First-ever tranche before any ingest: one snapshot, newer than latest.json.
  // Must render old→new (additions), never {from:null}.
  const meta = { "s.json": { fetched_at: "2026-06-12T12:07:04Z", card_count: 294 } };
  const out = selectDefaultPairWithCurrent(["s.json"], meta, "2026-05-27T13:48:27Z", SENT);
  assert.deepEqual(out, { from: SENT, to: "s.json" });
});

test("selectDefaultPairWithCurrent: single snapshot, @current equal → (snapshot, @current)", () => {
  const meta = { "s.json": { fetched_at: "2026-06-12T12:07:04Z" } };
  const out = selectDefaultPairWithCurrent(["s.json"], meta, "2026-06-12T12:07:04Z", SENT);
  assert.deepEqual(out, { from: "s.json", to: SENT });
});

test("selectDefaultPairWithCurrent: single snapshot, no current fetched_at → (snapshot, @current)", () => {
  const meta = { "s.json": { fetched_at: "2026-05-27T00:00:00Z" } };
  const out = selectDefaultPairWithCurrent(["s.json"], meta, undefined, SENT);
  assert.deepEqual(out, { from: "s.json", to: SENT });
});

test("selectDefaultPairWithCurrent: non-UTC offset timestamps compared by instant, not lexically", () => {
  // current = 2026-06-11T20:00Z (older), newest snapshot = 2026-06-11T23:00Z.
  // Lexicographically "2026-06-12T01:00:00+05:00" > "...23:00:00Z" would WRONGLY
  // treat @current as newer; by instant it is older → two newest snapshots.
  const index = ["a.json", "b.json"];
  const meta = { "b.json": { fetched_at: "2026-06-11T23:00:00Z" } };
  const out = selectDefaultPairWithCurrent(index, meta, "2026-06-12T01:00:00+05:00", SENT);
  assert.deepEqual(out, { from: "a.json", to: "b.json" });
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
    featured: false,
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

// --- row churn under a surviving card_id belongs to ROW-LEVEL CHANGES ---
//
// T47.3 established the row-truth claim: a duplicate card_id backed by a
// PDF row plus VID row(s) can lose or gain an individual row upstream
// while the id itself survives, and `Map.has(card_id)` — a set check — is
// blind to that, so the churn used to vanish from the page entirely. That
// claim stands and is pinned below.
//
// What changed is WHICH section owns those rows. T47.3 folded them into
// `diff.removed`/`diff.added`, but ADDED/REMOVED means a card_id entered
// or left the corpus — REMOVED is the same semantics the /removed surface
// publishes, and its entries link to /card pages. Folding row churn in
// made surviving cards render as REMOVED while linking to pages that
// still exist, AND rendered the same rows a second time under ROW-LEVEL
// CHANGES, while the receipt still counted whole-card removals only (site
// 6 vs receipt 3 on 596cc188→0d7e9ba1).
//
// So the two sections divide the work: `diffWithAliases` reports whole
// card_ids entering/leaving; `unpairedRowEntries` owns row churn within a
// surviving card_id. Nothing appears in both, and between them every
// disappearance is still surfaced.

test("row churn: duplicate card_id survives but loses a row → the lost row is an unpaired row, not a card removal", () => {
  const pdf = card("dup1", "PDF row", { asset_type: "PDF", asset_url: "u", video_title: null });
  const vidA = card("dup1", "VID A", {
    asset_type: "VID", asset_url: "u", video_title: "vt", dvids_video_id: "1",
  });
  const vidB = card("dup1", "VID B", {
    asset_type: "VID", asset_url: "u", video_title: "vt", dvids_video_id: "2",
  });
  const prev = [pdf, vidA, vidB];
  const curr = [pdf, vidA]; // vidB dropped upstream; dup1 itself still present
  const out = diffWithAliases(prev, curr, {});
  assert.equal(out.removed.length, 0, "dup1 is still in the corpus — not a removal");
  assert.equal(out.added.length, 0);
  // The row-truth claim T47.3 pinned: the dropped row is still surfaced.
  const rows = unpairedRowEntries(prev, curr);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].side, "prev");
  assert.equal(rows[0].row, vidB);
});

test("row churn: duplicate card_id survives but gains a row → the new row is an unpaired row, not a card addition", () => {
  const pdf = card("dup2", "PDF row", { asset_type: "PDF", asset_url: "u", video_title: null });
  const vidA = card("dup2", "VID A", {
    asset_type: "VID", asset_url: "u", video_title: "vt", dvids_video_id: "1",
  });
  const vidB = card("dup2", "VID B", {
    asset_type: "VID", asset_url: "u", video_title: "vt", dvids_video_id: "2",
  });
  const prev = [pdf, vidA];
  const curr = [pdf, vidA, vidB]; // vidB appears upstream
  const out = diffWithAliases(prev, curr, {});
  assert.equal(out.added.length, 0, "dup2 was already in the corpus — not an addition");
  assert.equal(out.removed.length, 0);
  const rows = unpairedRowEntries(prev, curr);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].side, "curr");
  assert.equal(rows[0].row, vidB);
});

test("row churn: single-row-id whose keying field mutates still pairs via the leftover rule → nothing in either section", () => {
  const prevRow = card("dup3", "row", { asset_type: "VID", asset_url: "u", video_title: "old title" });
  const currRow = card("dup3", "row", { asset_type: "VID", asset_url: "u", video_title: "new title" });
  const out = diffWithAliases([prevRow], [currRow], {});
  assert.equal(out.added.length, 0);
  assert.equal(out.removed.length, 0);
  assert.equal(unpairedRowEntries([prevRow], [currRow]).length, 0);
});

// --- T47.3: real-snapshot regression pins --------------------------------
//
// `596cc1881... -> 0d7e9ba1d5...` is the historical pair the bug was
// verified against: ea029a05470b8f4e drops from 6 rows to 4 (2 VID rows
// gone) and d8e5687dc870892d drops from 4 rows to 3 (1 VID row gone),
// while both card_ids survive. The old id-set diff reported only the 3
// card_ids that vanished entirely; the true removal count is 6.

function loadSnapshotCards(filename: string): CardMetadata[] {
  const raw = readFileSync(
    new URL(`../../../data/manifests/snapshots/${filename}`, import.meta.url),
    "utf-8",
  );
  return (JSON.parse(raw) as { cards: CardMetadata[] }).cards;
}

function pair596to0d7e(): { prev: CardMetadata[]; curr: CardMetadata[] } {
  return {
    prev: loadSnapshotCards(
      "596cc1881aa97d2fa49a45edab14d60802616e73ce125d286120e00d967cafa2.json",
    ),
    curr: loadSnapshotCards(
      "0d7e9ba1d51cded2d4839aac3b65d9ff14f56861c8338a57bbef50c8071d6731.json",
    ),
  };
}

test("regression 596cc188 -> 0d7e9ba1: REMOVED counts whole-card departures only — 3, matching the receipt", () => {
  const { prev, curr } = pair596to0d7e();
  const out = diffWithAliases(prev, curr, {});
  assert.equal(out.removed.length, 3, "3 card_ids left the corpus");
  assert.equal(out.added.length, 3);
  // ea029a05 and d8e5687d both survive this tranche — they lost rows, not
  // their card. A REMOVED entry for either would link to a /card page that
  // still exists.
  const removedIds = new Set(out.removed.map((c) => c.card_id));
  assert.ok(!removedIds.has("ea029a05470b8f4e"));
  assert.ok(!removedIds.has("d8e5687dc870892d"));
});

test("regression 596cc188 -> 0d7e9ba1: ROW-LEVEL CHANGES owns the 3 withdrawn rows of surviving cards", () => {
  const { prev, curr } = pair596to0d7e();
  const withdrawn = unpairedRowEntries(prev, curr).filter((u) => u.side === "prev");
  assert.equal(withdrawn.length, 3);
  const counts = withdrawn.reduce<Record<string, number>>((acc, u) => {
    acc[u.card_id] = (acc[u.card_id] ?? 0) + 1;
    return acc;
  }, {});
  assert.equal(counts["ea029a05470b8f4e"], 2);
  assert.equal(counts["d8e5687dc870892d"], 1);
});

test("regression 596cc188 -> 0d7e9ba1: all 6 disappearances still surface, 3+3 across the two sections", () => {
  // The row-truth claim T47.3 established, restated against the section
  // split: no disappearance was lost by moving row churn out of REMOVED.
  const { prev, curr } = pair596to0d7e();
  const removed = diffWithAliases(prev, curr, {}).removed;
  const withdrawn = unpairedRowEntries(prev, curr).filter((u) => u.side === "prev");
  assert.equal(removed.length + withdrawn.length, 6);
});

test("regression 596cc188 -> 0d7e9ba1: the two sections never render the same row twice", () => {
  // The double-render this pin exists to prevent: a row reachable from
  // both REMOVED and ROW-LEVEL CHANGES appeared on the page twice.
  const { prev, curr } = pair596to0d7e();
  const removedRows = new Set<CardMetadata>(diffWithAliases(prev, curr, {}).removed);
  const rowChangeRows = unpairedRowEntries(prev, curr).map((u) => u.row);
  for (const row of rowChangeRows) {
    assert.ok(!removedRows.has(row), `row of ${row.card_id} is in both sections`);
  }
  // …and no card_id spans the two sections either, so a reader never sees
  // one card described as both departed and merely churned.
  const removedIds = new Set([...removedRows].map((c) => c.card_id));
  for (const u of unpairedRowEntries(prev, curr)) {
    assert.ok(!removedIds.has(u.card_id), `${u.card_id} appears in both sections`);
  }
});

test("diffWithAliases regression: single-row-id tranche (0d7e9ba1 -> 65572b38) counts unchanged from today's output (T47.3)", () => {
  // This pair carries real add/remove churn (17/17) but no duplicate
  // card_id ever changes row count across it — a control pin proving the
  // row-multiset fix does not perturb the common single-row-id case.
  const prev = loadSnapshotCards(
    "0d7e9ba1d51cded2d4839aac3b65d9ff14f56861c8338a57bbef50c8071d6731.json",
  );
  const curr = loadSnapshotCards(
    "65572b38d27c3bc1af2c3206614913d4d491aea2b0d7d883e2334eaff3a44a8d.json",
  );
  const out = diffWithAliases(prev, curr, {});
  assert.equal(out.removed.length, 17);
  assert.equal(out.added.length, 17);
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

test("fieldOnlyChanges: featured flips false→true → reported", () => {
  const a = card("aaa", "T", { featured: false });
  const b = card("aaa", "T", { featured: true });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("featured"));
});

test("fieldOnlyChanges: featured unchanged true→true → no change", () => {
  const a = card("aaa", "T", { featured: true });
  const b = card("aaa", "T", { featured: true });
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
});

test("fieldOnlyChanges: redacted absent (old snapshot) vs redacted=false → NOT a spurious change", () => {
  // `redacted` joined the boolean-normalized fields alongside `featured`,
  // so it gets the same undefined≡false treatment. Guards the (desirable)
  // behavior change to a pre-existing field — a snapshot that predates an
  // always-present `redacted` must not flood the diff against an explicit
  // false.
  const prev = card("aaa", "T");
  delete (prev as { redacted?: boolean }).redacted;
  const sameFalse = card("aaa", "T", { redacted: false });
  assert.equal(fieldOnlyChanges([prev], [sameFalse]).length, 0);

  const nowTrue = card("aaa", "T", { redacted: true });
  const out = fieldOnlyChanges([prev], [nowTrue]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("redacted"));
});

test("fieldOnlyChanges: pre-Featured snapshot (field absent) vs featured=false → NOT a spurious change", () => {
  // Snapshots taken before the Featured column lack the field entirely
  // (undefined). Comparing against a new snapshot's explicit `false`
  // must NOT register as a change, or every non-featured card would
  // flood the diff. Only a real flip to `true` should surface.
  const prev = card("aaa", "T");
  delete (prev as { featured?: boolean }).featured; // simulate old wire shape
  const sameFalse = card("aaa", "T", { featured: false });
  assert.equal(fieldOnlyChanges([prev], [sameFalse]).length, 0);

  const nowTrue = card("aaa", "T", { featured: true });
  const out = fieldOnlyChanges([prev], [nowTrue]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("featured"));
});

// --- fieldOnlyChanges + pairRowsByCardId: duplicate card_id groups ---
//
// 9 ids in the 375-card manifest carry a PDF row plus one or more VID
// rows under the SAME card_id. Keying a Map by card_id (last row wins)
// and then diffing every curr row against that one survivor compares a
// VID row to a PDF row and fabricates field changes — "a video retitled
// into a PDF". These fixtures are built from the real duplicate ids in
// snapshot 5f5698f1 (verified against data/manifests/snapshots/).

// ea029a05470b8f4e — 1 PDF + 3 VID rows; the 3 VID rows share an
// identical (asset_url, asset_type, video_title) key and differ only by
// title (PR031 / PR032 / PR033), so they must be paired positionally.
const EA_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d32-mission-report,-syria-october-2024.pdf";
function ea029aRows(): CardMetadata[] {
  const vt = "Unresolved UAP Report, Syria, October 2024";
  return [
    card("ea029a05470b8f4e", "DOW-UAP-D032, Mission Report, Syria, October 2024", {
      asset_type: "PDF", asset_url: EA_URL, video_title: null, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR031, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR032, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
  ];
}

// d8e5687dc870892d — 1 PDF + 2 VID rows (PR026 / PR027, identical key).
const D8_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d23-mission-report-united-arab-emirates-october-2023.pdf";
function d8e56Rows(): CardMetadata[] {
  const vt = "Unresolved UAP Report, United Arab Emirates, October 2023";
  return [
    card("d8e5687dc870892d", "DOW-UAP-D023, Mission Report, United Arab Emirates, October 2023", {
      asset_type: "PDF", asset_url: D8_URL, video_title: null, incident_location: "Arabian Gulf",
    }),
    card("d8e5687dc870892d", "DOW-UAP-PR026, Unresolved UAP Report, United Arab Emirates, October 2023", {
      asset_type: "VID", asset_url: D8_URL, video_title: vt, incident_location: "United Arab Emirates",
    }),
    card("d8e5687dc870892d", "DOW-UAP-PR027, Unresolved UAP Report, United Arab Emirates, October 2023", {
      asset_type: "VID", asset_url: D8_URL, video_title: vt, incident_location: "United Arab Emirates",
    }),
  ];
}

// c1c59236394f7b14 — the 2-row shape: 1 PDF + 1 VID. Live, the buggy
// map diffed this id's VID row against its PDF row and asserted title,
// asset_type, incident_date, incident_location and description all
// changed — the exact regression this task fixes.
const C1_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d10-mission-report-middle-east-may-2022.pdf";
function c1c59Rows(): CardMetadata[] {
  return [
    card("c1c59236394f7b14", "DOW-UAP-D010, Mission Report, Middle East, May 2022", {
      asset_type: "PDF", asset_url: C1_URL, video_title: null, incident_location: "Iraq",
    }),
    card("c1c59236394f7b14", "DOW-UAP-PR019, Unresolved UAP Report, Middle East, May 2022", {
      asset_type: "VID", asset_url: C1_URL,
      video_title: "Unresolved UAP Report, Middle East, May 2022", incident_location: "Middle East",
    }),
  ];
}

test("fieldOnlyChanges: duplicate id (ea029a05, 4 rows) diffed against itself → 0 changes", () => {
  // Regression: the id-keyed map compared the PDF row and the first two
  // VID rows against the last VID row, fabricating title changes.
  assert.deepEqual(fieldOnlyChanges(ea029aRows(), ea029aRows()), []);
});

test("fieldOnlyChanges: duplicate id (d8e5687d, 3 rows) diffed against itself → 0 changes", () => {
  assert.deepEqual(fieldOnlyChanges(d8e56Rows(), d8e56Rows()), []);
});

test("fieldOnlyChanges: duplicate id (c1c59236, 2 rows PDF+VID) diffed against itself → 0 changes", () => {
  // The live symptom: a video 'retitled into a PDF'. A PDF row must only
  // ever be compared to a PDF row, so self-diff is empty.
  assert.deepEqual(fieldOnlyChanges(c1c59Rows(), c1c59Rows()), []);
});

test("fieldOnlyChanges: PDF row is only compared to PDF row, never to the VID row", () => {
  // Change ONLY the PDF row's title on the curr side. The result must
  // report a title change and NOTHING else — in particular never
  // asset_type or video_title, which would leak in if PDF were paired
  // with VID.
  const prev = c1c59Rows();
  const curr = c1c59Rows();
  curr[0] = { ...curr[0], title: "DOW-UAP-D010, Mission Report, Middle East, May 2022 (rev)" };
  const out = fieldOnlyChanges(prev, curr);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "c1c59236394f7b14");
  assert.deepEqual(out[0].fields, ["title"]);
});

test("fieldOnlyChanges: a change on one of several identical-key VID rows is paired positionally", () => {
  // The 3 ea029a05 VID rows share an identical pairing key. Changing the
  // middle VID row's incident_location must surface incident_location
  // (and nothing spurious like title, which stays put under positional
  // pairing PR032↔PR032).
  const prev = ea029aRows();
  const curr = ea029aRows();
  curr[2] = { ...curr[2], incident_location: "Türkiye" };
  const out = fieldOnlyChanges(prev, curr);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "ea029a05470b8f4e");
  assert.deepEqual(out[0].fields, ["incident_location"]);
});

// --- T47.4: skip-set semantics (was a 15-field allowlist) ----------------
//
// The allowlist silently dropped 107 real upstream changes across the
// corpus history: pdf_pairing (86), video_pairing (17), dvids_video_id
// (4) — never in `_COMPARED_FIELDS`, so a change to any of them rendered
// as no change at all on this page. Skip-set semantics compare
// everything except an explicit skip set, so a field is surfaced unless
// someone deliberately excludes it.

/**
 * Read a module-level `NAME = { "a", "b", ... }` set literal out of
 * `tranche.py`. Both exclusion sets are pinned this way rather than by
 * duplicating their members here, so adding a field on the Python side
 * without adding it on this one fails loudly instead of silently making
 * the receipt and the page describe a tranche differently.
 */
function pyFieldSet(pySrc: string, name: string): Set<string> {
  const match = new RegExp(`^${name}\\s*=\\s*\\{([^}]*)\\}`, "m").exec(pySrc);
  assert.ok(match, `tranche.py must still define ${name} as a module-level set literal`);
  const fields = new Set(Array.from(match[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]));
  assert.ok(fields.size > 0, `regex must actually find quoted field names in ${name}`);
  return fields;
}

function tranchePySource(): string {
  return readFileSync(new URL("../../../src/pursue_index/tranche.py", import.meta.url), "utf-8");
}

test("fieldOnlyChanges: DIFF_SKIP_FIELDS matches tranche.py's DIFF_SKIP_FIELDS exactly", () => {
  assert.deepEqual(
    DIFF_SKIP_FIELDS,
    pyFieldSet(tranchePySource(), "DIFF_SKIP_FIELDS"),
    "the site's skip set has drifted from tranche.py's — keep them identical",
  );
});

test("fieldOnlyChanges: LOCAL_CURATION_FIELDS matches tranche.py's LOCAL_CURATION_FIELDS exactly", () => {
  assert.deepEqual(
    LOCAL_CURATION_FIELDS,
    pyFieldSet(tranchePySource(), "LOCAL_CURATION_FIELDS"),
    "the site's curation-field set has drifted from tranche.py's — keep them identical",
  );
});

test("fieldOnlyChanges: the two exclusion sets stay disjoint and separately named", () => {
  // They are excluded for different reasons (pairing key + volatile
  // upstream metadata vs. our own editorial writes), and the receipt's
  // rationale comments are keyed to that split. A field drifting into
  // both would make either set's stated reason untrue for it.
  for (const f of LOCAL_CURATION_FIELDS) {
    assert.ok(!DIFF_SKIP_FIELDS.has(f), `${f} belongs to exactly one exclusion set`);
  }
  assert.ok(LOCAL_CURATION_FIELDS.size > 0 && DIFF_SKIP_FIELDS.size > 0);
});

test("fieldOnlyChanges: pdf_pairing change surfaces (previously silently dropped)", () => {
  const a = card("aaa", "T", { pdf_pairing: null });
  const b = card("aaa", "T", { pdf_pairing: "some-video-id" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["pdf_pairing"]);
});

test("fieldOnlyChanges: video_pairing change surfaces (previously silently dropped)", () => {
  const a = card("aaa", "T", { video_pairing: null });
  const b = card("aaa", "T", { video_pairing: "some-pdf-id" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["video_pairing"]);
});

test("fieldOnlyChanges: dvids_video_id change on a non-keying pair surfaces", () => {
  // dvids_video_id is also a row-pairing key (row-pairing.ts), but a
  // solo PDF row (no video_title siblings) still bucket-pairs 1:1 across
  // snapshots, so a dvids_video_id mutation reaches the field diff here
  // rather than only showing up as an add/remove of an unpaired row.
  const a = card("aaa", "T", { dvids_video_id: "111" });
  const b = card("aaa", "T", { dvids_video_id: "222" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["dvids_video_id"]);
});

// --- absent-vs-null parity with tranche.py (P0, post-T47.4) --------------
//
// `field_diff` reads both sides with `dict.get()`, so a key that is absent
// on one side and explicitly `null` on the other compares EQUAL. The
// union-of-keys loop here compared the raw values, and `undefined !== null`,
// so every snapshot schema addition — a manifest rebuilt after a new column
// exists carries it as `null` on rows with no value, while the older
// snapshot simply lacks the key — fabricated one "change" per row per new
// column on every historical pair.

test("fieldOnlyChanges: a field absent on prev and explicitly null on curr is not a change", () => {
  const a = card("aaa", "T");
  delete (a as Record<string, unknown>).original_classification;
  const b = card("aaa", "T", { original_classification: null });
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: a field explicitly null on prev and absent on curr is not a change", () => {
  const a = card("aaa", "T", { original_classification: null });
  const b = card("aaa", "T");
  delete (b as Record<string, unknown>).original_classification;
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: a field absent on prev and given a real value on curr is still a change", () => {
  // The absent==null rule must not swallow a genuine introduction of a
  // value — only the null/undefined serialization difference.
  const a = card("aaa", "T");
  delete (a as Record<string, unknown>).original_classification;
  const b = card("aaa", "T", { original_classification: "SECRET" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["original_classification"]);
});

// --- locally-curated fields are not upstream change (P0, post-T47.4) -----
//
// /diff describes what war.gov edited. The display_date_* family and
// `manifest_incident_date_raw` are written by OUR curation pipeline, so a
// snapshot taken after a curation pass differs from one taken before on
// every card we touched — hundreds of entries on a page whose whole claim
// is that it reports government edits.

test("fieldOnlyChanges: a display_date curated by us is not reported as an upstream change", () => {
  const a = card("aaa", "T", { display_date: null } as Partial<CardMetadata>);
  const b = card("aaa", "T", { display_date: "2023-10-24" } as Partial<CardMetadata>);
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: every LOCAL_CURATION_FIELDS entry is excluded", () => {
  for (const field of LOCAL_CURATION_FIELDS) {
    const a = card("aaa", "T", { [field]: null } as Partial<CardMetadata>);
    const b = card("aaa", "T", { [field]: "curated-value" } as Partial<CardMetadata>);
    assert.deepEqual(fieldOnlyChanges([a], [b]), [], `${field} must not be reported`);
  }
});

test("fieldOnlyChanges: a real upstream edit still reports alongside a curation field", () => {
  const a = card("aaa", "T", { display_date: null, incident_location: "Iraq" } as Partial<CardMetadata>);
  const b = card("aaa", "T", {
    display_date: "2023-10-24",
    incident_location: "Syria",
  } as Partial<CardMetadata>);
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["incident_location"]);
});

test("fieldOnlyChanges: card_id and raw are never reported even though they'd differ if compared", () => {
  // card_id is the pairing key so it can never itself differ within a
  // pair; this pins that the skip set still excludes it explicitly
  // rather than relying on that incidental fact.
  const a = card("aaa", "T");
  const b = card("aaa", "T");
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

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

test("pairRowsByCardId: ea029a05 group pairs all 4 rows (PDF↔PDF, 3 VID↔VID) with 0 unpaired", () => {
  const { pairs, unpaired } = pairRowsByCardId(ea029aRows(), ea029aRows());
  assert.equal(pairs.length, 4);
  assert.equal(unpaired.length, 0);
  // Every pair must be like-for-like on asset_type — never PDF↔VID.
  for (const p of pairs) assert.equal(p.prev.asset_type, p.curr.asset_type);
});

test("pairRowsByCardId: a dropped VID row is reported as unpaired (side prev), never dropped", () => {
  const prev = ea029aRows(); // 4 rows
  const curr = ea029aRows().slice(0, 3); // curr lost the last VID row
  const { pairs, unpaired } = pairRowsByCardId(prev, curr);
  assert.equal(pairs.length, 3);
  assert.equal(unpaired.length, 1);
  assert.equal(unpaired[0].side, "prev");
  assert.equal(unpaired[0].card_id, "ea029a05470b8f4e");
  assert.equal(unpaired[0].row.asset_type, "VID");
});

test("pairRowsByCardId: an added row is reported as unpaired (side curr), never dropped", () => {
  const prev = d8e56Rows().slice(0, 2); // PDF + 1 VID
  const curr = d8e56Rows(); // PDF + 2 VID → one extra
  const { pairs, unpaired } = pairRowsByCardId(prev, curr);
  assert.equal(pairs.length, 2);
  assert.equal(unpaired.length, 1);
  assert.equal(unpaired[0].side, "curr");
  assert.equal(unpaired[0].card_id, "d8e5687dc870892d");
});

test("pairRowsByCardId: card_id present on only one side is not reported here (add/remove, not a pairing)", () => {
  const prev = [card("only-prev", "P")];
  const curr = [card("only-curr", "C")];
  const { pairs, unpaired } = pairRowsByCardId(prev, curr);
  assert.deepEqual(pairs, []);
  assert.deepEqual(unpaired, []);
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
