/**
 * Row-pairing tests driven by the REAL snapshot manifests under
 * `data/manifests/snapshots/`.
 *
 * The /diff page pairs manifest rows within a card_id group before it
 * compares fields. 9 card_ids in the manifest carry a PDF row plus one
 * or more VID rows, so "one row per card_id" is not a valid assumption
 * anywhere in this path. These tests pin the pairing against actual
 * upstream data rather than hand-written literals: a self-diff of every
 * snapshot must be empty, and a known snapshot transition must report
 * exactly the fields that actually moved.
 *
 * Run via `npm run test:lib` (registered in web/package.json).
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import {
  describeUnpairedRow,
  fieldOnlyChanges,
  pairRowsByCardId,
  unpairedRowEntries,
} from "./diff-helpers.ts";
import type { CardMetadata } from "../data/types.ts";

const SNAPSHOT_DIR = new URL("../../../data/manifests/snapshots/", import.meta.url);

function snapshotFilenames(): string[] {
  return readdirSync(SNAPSHOT_DIR)
    .filter((f) => f.endsWith(".json") && f !== "index.json")
    .sort();
}

function loadSnapshot(filename: string): CardMetadata[] {
  const raw = readFileSync(new URL(filename, SNAPSHOT_DIR), "utf-8");
  return (JSON.parse(raw) as { cards: CardMetadata[] }).cards;
}

function loadByPrefix(prefix: string): CardMetadata[] {
  const match = snapshotFilenames().find((f) => f.startsWith(prefix));
  assert.ok(match, `no snapshot on disk starting with ${prefix}`);
  return loadSnapshot(match!);
}

// --- Self-diff: no snapshot may differ from itself -------------------

test("fieldOnlyChanges: every real snapshot diffed against itself → 0 changes", () => {
  const filenames = snapshotFilenames();
  assert.ok(filenames.length >= 10, "fixture set must be the real snapshot corpus");
  for (const f of filenames) {
    const cards = loadSnapshot(f);
    assert.deepEqual(fieldOnlyChanges(cards, cards), [], `${f} differs from itself`);
  }
});

test("pairRowsByCardId: every real snapshot pairs completely against itself (0 unpaired)", () => {
  for (const f of snapshotFilenames()) {
    const cards = loadSnapshot(f);
    const { pairs, unpaired } = pairRowsByCardId(cards, cards);
    assert.equal(pairs.length, cards.length, `${f}: not every row paired`);
    assert.deepEqual(unpaired, [], `${f}: rows left unpaired`);
  }
});

// --- Known upstream transitions --------------------------------------

test("fieldOnlyChanges: 13e730c1 → 5f5698f1 reports exactly 10 changes, all `featured`", () => {
  const out = fieldOnlyChanges(loadByPrefix("13e730c1"), loadByPrefix("5f5698f1"));
  assert.equal(out.length, 10);
  for (const fc of out) assert.deepEqual(fc.fields, ["featured"]);
});

test("fieldOnlyChanges: c9cc83fc → f75e2f7d reports the asset_type VID→AUD change on 167f6a21c7238d0c", () => {
  // asset_type is a COMPARED field, so it must not be part of the pairing
  // key — keying on it means a row whose asset_type moves never pairs and
  // the change is never reported.
  const prev = loadByPrefix("c9cc83fc");
  const curr = loadByPrefix("f75e2f7d");
  const target = "167f6a21c7238d0c";
  assert.equal(prev.filter((c) => c.card_id === target)[0].asset_type, "VID");
  assert.equal(curr.filter((c) => c.card_id === target)[0].asset_type, "AUD");

  const out = fieldOnlyChanges(prev, curr);
  const hit = out.find((fc) => fc.card_id === target);
  assert.ok(hit, "asset_type change on 167f6a21c7238d0c was not reported");
  assert.ok(hit!.fields.includes("asset_type"));
});

// --- Single-row mutation on a keying-adjacent field -------------------

test("fieldOnlyChanges: a single-row card whose asset_url changes → reported", () => {
  const prev = loadByPrefix("f75e2f7d");
  const single = prev.find(
    (c) => prev.filter((o) => o.card_id === c.card_id).length === 1 && !!c.asset_url,
  );
  assert.ok(single, "expected at least one single-row card with an asset_url");
  const curr = prev.map((c) =>
    c === single ? { ...c, asset_url: `${c.asset_url}?rev=2` } : c,
  );
  const out = fieldOnlyChanges(prev, curr);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, single!.card_id);
  assert.deepEqual(out[0].fields, ["asset_url"]);
});

// --- Row order is not content ----------------------------------------

test("fieldOnlyChanges: reordering the identical VID rows of ea029a05470b8f4e → 0 changes", () => {
  // The 3 VID rows under this id share asset_url and video_title and are
  // distinguished only by dvids_video_id. Upstream row order is not a
  // fact about the cards, so a reorder must not read as a retitle.
  const prev = loadByPrefix("5f5698f1");
  const target = "ea029a05470b8f4e";
  const vids = prev.filter((c) => c.card_id === target && c.asset_type === "VID");
  assert.equal(vids.length, 3, "fixture assumption: 3 VID rows under this id");

  const reversed = [...vids].reverse();
  let i = 0;
  const curr = prev.map((c) =>
    c.card_id === target && c.asset_type === "VID" ? reversed[i++] : c,
  );
  assert.deepEqual(fieldOnlyChanges(prev, curr), []);
});

// --- Unpaired rows are surfaced, never dropped ------------------------

test("unpairedRowEntries: an added 4th VID row under ea029a05470b8f4e is surfaced", () => {
  const prev = loadByPrefix("5f5698f1");
  const target = "ea029a05470b8f4e";
  const existing = prev.find((c) => c.card_id === target && c.asset_type === "VID")!;
  const extra: CardMetadata = {
    ...existing,
    dvids_video_id: "9999999",
    title: "DOW-UAP-PR034, Unresolved UAP Report, Syria, October 2024",
  };
  const curr = [...prev, extra];

  const entries = unpairedRowEntries(prev, curr);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].card_id, target);
  assert.equal(entries[0].side, "curr");
  assert.equal(entries[0].row.dvids_video_id, "9999999");
});

test("unpairedRowEntries: a withdrawn VID row under ea029a05470b8f4e is surfaced", () => {
  const curr = loadByPrefix("5f5698f1");
  const target = "ea029a05470b8f4e";
  const dropped = curr.filter((c) => c.card_id === target && c.asset_type === "VID")[2];
  const prev = curr;
  const shrunk = curr.filter((c) => c !== dropped);

  const entries = unpairedRowEntries(prev, shrunk);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].card_id, target);
  assert.equal(entries[0].side, "prev");
  assert.equal(entries[0].row.dvids_video_id, dropped.dvids_video_id);
});

test("unpairedRowEntries: no row churn → empty", () => {
  const cards = loadByPrefix("5f5698f1");
  assert.deepEqual(unpairedRowEntries(cards, cards), []);
});

// --- Display shape for the /diff row-change section -------------------

test("describeUnpairedRow: a curr-side row reads as ADDED, a prev-side row as WITHDRAWN", () => {
  const cards = loadByPrefix("5f5698f1");
  const row = cards.find((c) => c.card_id === "ea029a05470b8f4e" && c.asset_type === "VID")!;

  const added = describeUnpairedRow({ card_id: row.card_id, side: "curr", row });
  assert.equal(added.verb, "ADDED");
  assert.equal(added.symbol, "+");
  assert.equal(added.assetType, "VID");
  assert.equal(added.title, row.title);
  assert.equal(added.cardId, "ea029a05470b8f4e");
  assert.ok(added.detail.includes(row.dvids_video_id!));

  const withdrawn = describeUnpairedRow({ card_id: row.card_id, side: "prev", row });
  assert.equal(withdrawn.verb, "WITHDRAWN");
  assert.equal(withdrawn.symbol, "−");
});

test("describeUnpairedRow: a row with no dvids_video_id still gets a detail string", () => {
  const cards = loadByPrefix("5f5698f1");
  const pdf = cards.find((c) => c.asset_type === "PDF" && !c.dvids_video_id)!;
  const out = describeUnpairedRow({ card_id: pdf.card_id, side: "curr", row: pdf });
  assert.ok(out.detail.length > 0);
  assert.ok(!out.detail.includes("null"));
});
