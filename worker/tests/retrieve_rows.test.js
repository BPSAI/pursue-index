// The Worker reads page title/text from the sharded retrieval payload
// (data/retrieve/, built by scripts/build_retrieve_rows.py) instead of
// parsing all of pages.json: only the shards holding the wanted rows are
// fetched, one at a time, and each is dropped once its rows are copied out.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { loadRowsManifest, loadRows, loadTitles } from "../retrieve_rows.js";
import { filesAssets, publishRetrieveRows } from "./support/retrieve_payload.js";

const indexPages = [["a", 1], ["a", 2], ["b", 1], ["ghost", 1], ["c", 1]];
const pagesArr = [
  { card_id: "b", page: 1, title: "DOW-UAP-D017 B", text: "bee" },
  { card_id: "a", page: 1, title: "A", text: "ay one" },
  { card_id: "a", page: 2, title: "A", text: "ay two" },
  { card_id: "c", page: 1, title: "C", text: "see" },
];

function setup() {
  const files = publishRetrieveRows(new Map(), indexPages, pagesArr, { rowsPerShard: 2 });
  const log = [];
  const assets = filesAssets(files, log);
  return { files, log, fetchFn: (u) => assets.fetch(u) };
}

describe("loadRows", () => {
  test("fetches only the shards holding the wanted rows, in shard order", async () => {
    const { log, fetchFn } = setup();
    const manifest = await loadRowsManifest(fetchFn);
    log.length = 0;
    const rows = await loadRows(fetchFn, manifest, [4, 0, 1]);
    assert.deepEqual(log, ["retrieve/rows-0-000000000000.json", "retrieve/rows-4-000000000004.json"]);
    assert.deepEqual(rows.get(0), { card_id: "a", page: 1, title: "A", text: "ay one" });
    assert.deepEqual(rows.get(1), { card_id: "a", page: 2, title: "A", text: "ay two" });
    assert.deepEqual(rows.get(4), { card_id: "c", page: 1, title: "C", text: "see" });
    assert.equal(rows.size, 3);
  });

  test("a row with no page record is absent, not blank", async () => {
    const { fetchFn } = setup();
    const manifest = await loadRowsManifest(fetchFn);
    const rows = await loadRows(fetchFn, manifest, [3, 2]);
    assert.equal(rows.has(3), false);
    assert.equal(rows.get(2).card_id, "b");
  });

  test("no wanted rows, no fetches", async () => {
    const { log, fetchFn } = setup();
    const manifest = await loadRowsManifest(fetchFn);
    log.length = 0;
    assert.equal((await loadRows(fetchFn, manifest, [])).size, 0);
    assert.deepEqual(log, []);
  });

  test("a shard that disagrees with the manifest throws", async () => {
    const { files, fetchFn } = setup();
    files.set("retrieve/rows-2-000000000002.json", JSON.stringify([["b", 1, "B", "bee"]]));
    const manifest = await loadRowsManifest(fetchFn);
    await assert.rejects(loadRows(fetchFn, manifest, [2]), /rows-2-000000000002\.json/);
  });

  test("a missing manifest is an error naming it", async () => {
    await assert.rejects(loadRowsManifest(async () => new Response("nf", { status: 404 })), /rows\.json/);
  });
});

describe("loadTitles", () => {
  test("one {card_id, title} per card, in first-page order", async () => {
    const { fetchFn } = setup();
    const titles = await loadTitles(fetchFn, await loadRowsManifest(fetchFn));
    assert.deepEqual([...titles.values()], [
      { card_id: "b", title: "DOW-UAP-D017 B" },
      { card_id: "a", title: "A" },
      { card_id: "c", title: "C" },
    ]);
  });
});
