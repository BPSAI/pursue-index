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
  pairRowsByCardId,
  selectDefaultPair,
  selectDefaultPairWithCurrent,
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
