// Tests for the /api/retrieve handler with mocked ASSETS + Voyage.
//
// Strategy: build a tiny fixture corpus (n=4, dim=3), wrap it in a mock
// env.ASSETS that serves embeddings.bin (float16) + embed_index.json +
// pages.json. Inject a fake embedQuery via the retrievePassages
// signature. Verify the response shape, ordering, and threshold filter.

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  retrievePassages,
  handleRetrieve,
  _resetCaches,
} from "../retrieve.js";

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

function makeMockEnv(rows, indexPages, pagesArr, voyageVec) {
  const corpusBuf = floatsToFloat16Buffer(rows);
  const indexJson = {
    model_id: "voyage-3",
    dim: rows[0].length,
    n: rows.length,
    pages: indexPages,
  };
  const ASSETS = {
    fetch: async (urlOrReq) => {
      const url = typeof urlOrReq === "string" ? urlOrReq : urlOrReq.url;
      if (url.endsWith("/data/embeddings.bin")) {
        return new Response(corpusBuf, { status: 200 });
      }
      if (url.endsWith("/data/embed_index.json")) {
        return new Response(JSON.stringify(indexJson), { status: 200 });
      }
      if (url.endsWith("/data/pages.json")) {
        return new Response(JSON.stringify(pagesArr), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    },
  };
  return {
    env: { ASSETS, VOYAGE_API_KEY: "test" },
    embedFn: async () => new Float32Array(voyageVec),
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
    // The index row survives but pages.json has no entry for it — the
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
  test("embeddings.bin and pages.json published as parts load identically", async () => {
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
    const pagesBytes = new TextEncoder().encode(JSON.stringify(pagesArr));
    const files = new Map();
    function publish(name, bytes, cut) {
      const parts = [bytes.slice(0, cut), bytes.slice(cut)];
      parts.forEach((b, i) => files.set(`${name}.part-00${i}${name.slice(name.lastIndexOf("."))}`, b));
      files.set(`${name}.chunks.json`, JSON.stringify({
        name,
        size: bytes.length,
        parts: parts.map((b, i) => ({
          path: `${name}.part-00${i}${name.slice(name.lastIndexOf("."))}`,
          size: b.length,
        })),
      }));
    }
    publish("embeddings.bin", corpus, 7);
    publish("pages.json", pagesBytes, 33);
    files.set("embed_index.json", JSON.stringify({ model_id: "voyage-3", dim: 3, n: 3, pages: indexPages }));
    const env = {
      ASSETS: {
        fetch: async (u) => {
          const name = String(u).split("/data/")[1];
          return files.has(name)
            ? new Response(files.get(name), { status: 200 })
            : new Response("not found", { status: 404 });
        },
      },
      VOYAGE_API_KEY: "test",
    };
    const out = await retrievePassages("Roswell", 8, env, async () => new Float32Array([0, 1, 0]));
    assert.equal(out.length, 1);
    assert.equal(out[0].card_id, "card-b");
    assert.ok(out[0].snippet.includes("Roswell"));
  });
});

// ---------------------------------------------------------------------------
// Embedding load memory profile. A cold isolate must not hold the fetched
// parts, an assembled copy and the Float32Array at once (Workers isolates
// have 128 MB): vectors are decoded part by part, straight from each
// response stream, into one preallocated Float32Array.
// ---------------------------------------------------------------------------

import { decodeFloat16Asset, float16ToFloat32 } from "../retrieve.js";

function refusingStream(bytes, chunk, log, name) {
  let at = 0;
  const body = new ReadableStream({
    pull(controller) {
      if (at >= bytes.length) {
        log.push(`end ${name}`);
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(at, at + chunk));
      at += chunk;
    },
  });
  const refuse = () => {
    throw new Error(`whole-body read of ${name}`);
  };
  return { ok: true, status: 200, body, arrayBuffer: refuse, json: refuse, text: refuse, bytes: refuse };
}

function chunkedAssets(name, bytes, cuts, { chunk = 3, log = [] } = {}) {
  const ext = name.slice(name.lastIndexOf("."));
  const edges = [0, ...cuts, bytes.length];
  const parts = edges.slice(0, -1).map((s, i) => [`${name}.part-00${i}${ext}`, bytes.slice(s, edges[i + 1])]);
  const manifest = JSON.stringify({
    name,
    size: bytes.length,
    parts: parts.map(([path, b]) => ({ path, size: b.length })),
  });
  return { parts, manifest, chunk, log };
}

describe("decodeFloat16Asset", () => {
  // Every float16 bit pattern class: zeros, subnormals, normals, inf, NaN.
  const u16 = Uint16Array.from({ length: 64 }, (_, i) => (i * 2654435761) >>> 16);
  u16.set([0x0000, 0x8000, 0x0001, 0x03ff, 0x3c00, 0xbc00, 0x7c00, 0xfc00, 0x7e00], 0);
  const whole = new Uint8Array(u16.buffer.slice(0));

  test("decodes parts that split mid-value to exactly the single-file decode", async () => {
    const log = [];
    // Odd part sizes and 3-byte stream chunks: every float straddles a boundary somewhere.
    const a = chunkedAssets("embeddings.bin", whole, [37, 81], { log });
    const fetchFn = async (url) => {
      const name = url.slice(url.lastIndexOf("/") + 1);
      log.push(`fetch ${name}`);
      if (name === "embeddings.bin.chunks.json") return new Response(a.manifest);
      const part = a.parts.find(([p]) => p === name);
      return refusingStream(part[1], a.chunk, log, name);
    };
    const out = await decodeFloat16Asset("https://assets/data/embeddings.bin", fetchFn, u16.length);
    const expected = float16ToFloat32(whole.buffer);
    assert.deepEqual(new Uint32Array(out.buffer), new Uint32Array(expected.buffer), "bitwise equal");
    // Sequential: a part is fetched only after the previous one was fully read,
    // and no part body was ever read whole (arrayBuffer/json/text throw).
    assert.deepEqual(log, [
      "fetch embeddings.bin.chunks.json",
      "fetch embeddings.bin.part-000.bin", "end embeddings.bin.part-000.bin",
      "fetch embeddings.bin.part-001.bin", "end embeddings.bin.part-001.bin",
      "fetch embeddings.bin.part-002.bin", "end embeddings.bin.part-002.bin",
    ]);
  });

  test("rejects a payload whose size disagrees with the index", async () => {
    const fetchFn = async (url) =>
      url.endsWith(".chunks.json") ? new Response("nf", { status: 404 }) : new Response(whole);
    await assert.rejects(
      decodeFloat16Asset("https://assets/data/embeddings.bin", fetchFn, u16.length + 1),
      /embeddings\.bin/,
    );
    await assert.rejects(
      decodeFloat16Asset("https://assets/data/embeddings.bin", fetchFn, u16.length - 1),
      /embeddings\.bin/,
    );
  });
});

describe("retrievePassages load order", () => {
  test("pages.json and the vectors load one after the other, never overlapping", async () => {
    const rows = [
      [1, 0, 0],
      [0, 1, 0],
    ];
    const corpus = new Uint8Array(floatsToFloat16Buffer(rows));
    const log = [];
    const emb = chunkedAssets("embeddings.bin", corpus, [5], { log });
    const pagesArr = [
      { card_id: "a", page: 1, title: "A", text: "Apollo" },
      { card_id: "b", page: 1, title: "B", text: "Roswell" },
    ];
    const env = {
      VOYAGE_API_KEY: "test",
      ASSETS: {
        fetch: async (u) => {
          const name = String(u).split("/data/")[1];
          log.push(`fetch ${name}`);
          if (name === "embeddings.bin.chunks.json") return new Response(emb.manifest);
          const part = emb.parts.find(([p]) => p === name);
          if (part) return refusingStream(part[1], emb.chunk, log, name);
          if (name === "embed_index.json")
            return new Response(JSON.stringify({ model_id: "voyage-3", dim: 3, n: 2, pages: [["a", 1], ["b", 1]] }));
          if (name === "pages.json") return new Response(JSON.stringify(pagesArr));
          return new Response("nf", { status: 404 });
        },
      },
    };
    const out = await retrievePassages("Roswell", 8, env, async () => new Float32Array([0, 1, 0]));
    assert.equal(out[0].card_id, "b");
    // pages.json is read in full (a plain Response, consumed before
    // loadPages returns) before the first embeddings request is made.
    const pagesFetch = log.indexOf("fetch pages.json");
    const firstEmbeddings = log.indexOf("fetch embeddings.bin.chunks.json");
    assert.ok(pagesFetch >= 0 && firstEmbeddings > pagesFetch, log.join(" | "));
    assert.equal(log.at(-1), "end embeddings.bin.part-001.bin", log.join(" | "));
  });
});
