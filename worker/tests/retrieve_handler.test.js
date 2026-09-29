// Tests for the /api/retrieve handler with mocked ASSETS + Voyage.
//
// Strategy: build a tiny fixture corpus (n=4, dim=3), wrap it in a mock
// env.ASSETS that serves embeddings.bin (float16) + embed_index.json +
// the sharded retrieval rows (data/retrieve/). Inject a fake embedQuery via the retrievePassages
// signature. Verify the response shape, ordering, and threshold filter.

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  retrievePassages,
  handleRetrieve,
  _resetCaches,
} from "../retrieve.js";
import { filesAssets, publishRetrieveRows } from "./support/retrieve_payload.js";

// Pack a Float32 array to Float16 bytes the same way Voyage ships them.
function floatsToFloat16Buffer(rows) {
  const dim = rows[0].length;
  const u16 = new Uint16Array(rows.length * dim);
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = 0; j < dim; j += 1) {
      u16[i * dim + j] = floatToHalf(rows[i][j]);
    }
  }
  return u16.buffer;
}

function floatToHalf(f) {
  if (f === 0) return 0;
  const sign = f < 0 ? 1 : 0;
  const a = Math.abs(f);
  const e = Math.floor(Math.log2(a));
  const exp = e + 15;
  const frac = Math.round((a / Math.pow(2, e) - 1) * 1024);
  if (exp <= 0 || exp >= 31) {
    // Out of range; for our test fixture all values fit easily.
    throw new Error("float16 overflow in test fixture");
  }
  return (sign << 15) | (exp << 10) | (frac & 0x3ff);
}

function makeMockEnv(rows, indexPages, pagesArr, voyageVec, log = []) {
  const files = publishRetrieveRows(new Map(), indexPages, pagesArr);
  files.set("embeddings.bin", new Uint8Array(floatsToFloat16Buffer(rows)));
  files.set(
    "embed_index.json",
    JSON.stringify({ model_id: "voyage-3", dim: rows[0].length, n: rows.length, pages: indexPages }),
  );
  return {
    env: { ASSETS: filesAssets(files, log), VOYAGE_API_KEY: "test" },
    embedFn: async () => new Float32Array(voyageVec),
    files,
  };
}

beforeEach(() => _resetCaches());

describe("retrievePassages", () => {
  test("returns top-k passages ordered by score with title+snippet", async () => {
    // Three corpus rows; the query is most similar to row 1.
    const rows = [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ];
    const indexPages = [
      ["card-a", 1],
      ["card-b", 2],
      ["card-c", 3],
    ];
    const pagesArr = [
      { id: "card-a-p1", card_id: "card-a", page: 1, title: "A", text: "Apollo report" },
      { id: "card-b-p2", card_id: "card-b", page: 2, title: "B", text: "Roswell file" },
      { id: "card-c-p3", card_id: "card-c", page: 3, title: "C", text: "Other" },
    ];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    const out = await retrievePassages("Roswell", 8, env, embedFn);
    assert.equal(out.length, 1, "threshold filters to the one matching row");
    assert.equal(out[0].card_id, "card-b");
    assert.equal(out[0].page, 2);
    assert.equal(out[0].title, "B");
    assert.ok(out[0].score > 0.99);
    assert.ok(out[0].snippet.includes("Roswell"));
  });

  test("threshold filters out low-score hits", async () => {
    const rows = [
      [1, 0, 0],
      [0.6, 0.6, 0.5], // mid score
      [0, 0, 1],
    ];
    const indexPages = [
      ["a", 1],
      ["b", 1],
      ["c", 1],
    ];
    const pagesArr = [
      { id: "a-p1", card_id: "a", page: 1, title: "A", text: "x" },
      { id: "b-p1", card_id: "b", page: 1, title: "B", text: "x" },
      { id: "c-p1", card_id: "c", page: 1, title: "C", text: "x" },
    ];
    // Query asks for [1, 0, 0] direction.
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [1, 0, 0]);
    const out = await retrievePassages("q", 8, env, embedFn);
    // Row 0 perfect match; row 1 score ~0.65 → still passes 0.5; row 2 0.
    assert.equal(out.length, 2);
    assert.equal(out[0].card_id, "a");
    assert.equal(out[1].card_id, "b");
  });

  test("skips a hit whose page record is missing, and logs it", async () => {
    // The index row survives but the retrieval rows have no entry for it — the
    // shape a superseded or withdrawn row leaves behind. Emitting it
    // would produce a citation with a blank title and snippet.
    const rows = [
      [1, 0, 0],
      [0, 1, 0],
    ];
    const indexPages = [["ghost", 1], ["b", 1]];
    const pagesArr = [
      { id: "b-p1", card_id: "b", page: 1, title: "B", text: "Roswell file" },
    ];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [1, 0, 0]);
    const warnings = [];
    const realWarn = console.warn;
    console.warn = (...args) => warnings.push(args.join(" "));
    try {
      const out = await retrievePassages("q", 8, env, embedFn);
      assert.equal(out.length, 0, "the only in-threshold hit was skipped");
      assert.equal(warnings.length, 1);
      assert.match(warnings[0], /ghost-p1/);
    } finally {
      console.warn = realWarn;
    }
  });

  test("never emits a citation with an empty title or snippet", async () => {
    const rows = [
      [1, 0, 0],
      [0.9, 0.1, 0],
      [0.8, 0.2, 0],
    ];
    const indexPages = [["a", 1], ["b", 1], ["c", 1]];
    const pagesArr = [
      { id: "a-p1", card_id: "a", page: 1, title: "", text: "no title here" },
      { id: "b-p1", card_id: "b", page: 1, title: "B", text: "   " },
      { id: "c-p1", card_id: "c", page: 1, title: "C", text: "readable text" },
    ];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [1, 0, 0]);
    const realWarn = console.warn;
    console.warn = () => {};
    try {
      const out = await retrievePassages("q", 8, env, embedFn);
      assert.equal(out.length, 1);
      assert.equal(out[0].card_id, "c");
      for (const p of out) {
        assert.ok(p.title.trim().length > 0);
        assert.ok(p.snippet.trim().length > 0);
      }
    } finally {
      console.warn = realWarn;
    }
  });

  test("returns empty array if no hit clears threshold", async () => {
    const rows = [
      [0, 1, 0],
      [0, 0, 1],
    ];
    const indexPages = [["a", 1], ["b", 1]];
    const pagesArr = [
      { id: "a-p1", card_id: "a", page: 1, title: "A", text: "x" },
      { id: "b-p1", card_id: "b", page: 1, title: "B", text: "x" },
    ];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [1, 0, 0]);
    const out = await retrievePassages("q", 8, env, embedFn);
    assert.equal(out.length, 0);
  });
});

describe("handleRetrieve", () => {
  test("400 on missing query", async () => {
    // Only the gate matters; ASSETS won't be hit because the validation
    // is up-front.
    const env = { ASSETS: { fetch: async () => new Response("404", { status: 404 }) } };
    const req = new Request("https://x/api/retrieve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const r = await handleRetrieve(req, env);
    assert.equal(r.status, 400);
  });

  test("405 on GET", async () => {
    const env = { ASSETS: { fetch: async () => new Response("ok") } };
    const r = await handleRetrieve(
      new Request("https://x/api/retrieve", { method: "GET" }),
      env,
    );
    assert.equal(r.status, 405);
  });

  test("400 on query > 1000 chars", async () => {
    const env = { ASSETS: { fetch: async () => new Response("ok") } };
    const req = new Request("https://x/api/retrieve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "a".repeat(1001) }),
    });
    const r = await handleRetrieve(req, env);
    assert.equal(r.status, 400);
  });
});

describe("chunked corpus payloads", () => {
  test("embeddings.bin published as parts loads identically", async () => {
    const rows = [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ];
    const indexPages = [
      ["card-a", 1],
      ["card-b", 2],
      ["card-c", 3],
    ];
    const pagesArr = [
      { card_id: "card-a", page: 1, title: "A", text: "Apollo report" },
      { card_id: "card-b", page: 2, title: "B", text: "Roswell file" },
      { card_id: "card-c", page: 3, title: "C", text: "Other" },
    ];
    const corpus = new Uint8Array(floatsToFloat16Buffer(rows));
    const files = publishRetrieveRows(new Map(), indexPages, pagesArr);
    function publish(name, bytes, cut) {
      const parts = [bytes.slice(0, cut), bytes.slice(cut)];
      parts.forEach((b, i) => files.set(`${name}.part-00${i}-0123456789ab${name.slice(name.lastIndexOf("."))}`, b));
      files.set(`${name}.chunks.json`, JSON.stringify({
        name,
        size: bytes.length,
        parts: parts.map((b, i) => ({
          path: `${name}.part-00${i}-0123456789ab${name.slice(name.lastIndexOf("."))}`,
          size: b.length,
        })),
      }));
    }
    publish("embeddings.bin", corpus, 7);
    files.set("embed_index.json", JSON.stringify({ model_id: "voyage-3", dim: 3, n: 3, pages: indexPages }));
    const env = { ASSETS: filesAssets(files), VOYAGE_API_KEY: "test" };
    const out = await retrievePassages("Roswell", 8, env, async () => new Float32Array([0, 1, 0]));
    assert.equal(out.length, 1);
    assert.equal(out[0].card_id, "card-b");
    assert.ok(out[0].snippet.includes("Roswell"));
  });
});

// ---------------------------------------------------------------------------
// Cold-path shape. A cold isolate must not parse pages.json, must load the
// vectors once however many requests arrive together, and must fetch only
// the retrieval shards holding the rows it cites.
// ---------------------------------------------------------------------------

describe("retrievePassages cold path", () => {
  const rows = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0.1, 0.9, 0],
  ];
  const indexPages = [["a", 1], ["b", 1], ["c", 1], ["d", 1]];
  const pagesArr = [
    { card_id: "a", page: 1, title: "A", text: "Apollo" },
    { card_id: "b", page: 1, title: "B", text: "Roswell" },
    { card_id: "c", page: 1, title: "C", text: "Other" },
    { card_id: "d", page: 1, title: "D", text: "Roswell too" },
  ];

  test("never fetches pages.json; fetches only the shards holding the hits", async () => {
    const log = [];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0], log);
    const out = await retrievePassages("Roswell", 8, env, embedFn);
    assert.deepEqual(out.map((p) => p.card_id), ["b", "d"]);
    assert.ok(!log.some((n) => n.startsWith("pages.json")), log.join(" | "));
    // Rows 1 and 3 live in shards 0 (rows 0-1) and 2 (rows 2-3): both needed.
    const shards = log.filter((n) => /^retrieve\/rows-\d/.test(n));
    assert.deepEqual(shards, ["retrieve/rows-0-000000000000.json", "retrieve/rows-2-000000000002.json"]);
  });

  test("concurrent cold requests load the index and vectors once", async () => {
    const log = [];
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0], log);
    const outs = await Promise.all([1, 2, 3].map(() => retrievePassages("Roswell", 8, env, embedFn)));
    for (const out of outs) assert.equal(out[0].card_id, "b");
    const count = (name) => log.filter((n) => n === name).length;
    assert.equal(count("embeddings.bin"), 1, log.join(" | "));
    assert.equal(count("embed_index.json"), 1, log.join(" | "));
    assert.equal(count("retrieve/rows.json"), 1, log.join(" | "));
  });

  test("a load failure is not cached: the next request retries", async () => {
    const log = [];
    const { env, embedFn, files } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0], log);
    const bin = files.get("embeddings.bin");
    files.delete("embeddings.bin");
    await assert.rejects(retrievePassages("Roswell", 8, env, embedFn), /embeddings\.bin/);
    files.set("embeddings.bin", bin);
    const out = await retrievePassages("Roswell", 8, env, embedFn);
    assert.equal(out[0].card_id, "b");
  });

  test("a shard row that disagrees with the index row is skipped, logged", async () => {
    const { env, embedFn, files } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    // Rows drifted: shard 0's row 1 now describes another page.
    files.set("retrieve/rows-0-000000000000.json", JSON.stringify([["a", 1, "A", "Apollo"], ["zz", 9, "Z", "Roswell"]]));
    const warnings = [];
    const realWarn = console.warn;
    console.warn = (...args) => warnings.push(args.join(" "));
    try {
      const out = await retrievePassages("Roswell", 8, env, embedFn);
      assert.deepEqual(out.map((p) => p.card_id), ["d"]);
      assert.ok(warnings.some((w) => /b-p1/.test(w)), warnings.join(" | "));
    } finally {
      console.warn = realWarn;
    }
  });

  test("literal slug and card_id lanes cite from the shards", async () => {
    const slugPages = pagesArr.map((p) => (p.card_id === "c" ? { ...p, title: "DOW-UAP-D017, Other" } : p));
    const hexIndex = [["a", 1], ["b", 1], ["0123456789abcdef", 1], ["d", 1]];
    const hexPages = slugPages.map((p) => (p.card_id === "c" ? { ...p, card_id: "0123456789abcdef" } : p));
    const { env, embedFn } = makeMockEnv(rows, hexIndex, hexPages, [0, 1, 0]);
    const bySlug = await retrievePassages("what is DOW-UAP-D017?", 8, env, embedFn);
    assert.equal(bySlug[0].card_id, "0123456789abcdef");
    assert.equal(bySlug[0].score, 1.0);
    const byId = await retrievePassages("card 0123456789abcdef please", 8, env, embedFn);
    assert.equal(byId[0].card_id, "0123456789abcdef");
    assert.equal(byId[0].title, "DOW-UAP-D017, Other");
  });
});
