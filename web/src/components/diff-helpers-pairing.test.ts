/**
 * Tests for the pairing/selection layer of the /diff page's pure helper
 * module: URL param round-trip, default-pair selection, alias-aware
 * add/remove/renamed grouping, row-level churn under a surviving
 * card_id, and duplicate-card_id row pairing.
 *
 * Run with: `node --test src/components/diff-helpers-pairing.test.ts`
 * (the project's web-side test convention — see existing
 * `atlas-helpers.test.ts` for the same pattern).
 *
 * Split out of `diff-helpers.test.ts` (T48.10) along its existing
 * `// --- section ---` seams — see the sibling
 * `diff-helpers-field-changes.test.ts` and `diff-helpers-report.test.ts`
 * for the rest of that file's coverage. Row fixtures shared across the
 * split live in `diff-test-fixtures.ts`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  parseDiffParams,
  buildDiffParams,
  resolveAliases,
  diffWithAliases,
  pairRowsByCardId,
  unpairedRowEntries,
  selectDefaultPair,
  selectDefaultPairWithCurrent,
} from "./diff-helpers.ts";
import { card, ea029aRows, d8e56Rows } from "./diff-test-fixtures.ts";
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

// --- pairRowsByCardId: duplicate card_id groups ---

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
