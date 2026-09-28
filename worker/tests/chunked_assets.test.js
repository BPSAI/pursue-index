// Public /data URLs of payloads published as parts keep working: the
// Worker reassembles `/data/<name>` from `<name>.chunks.json` + parts when
// the whole file is not among the static assets (it is over the 25 MiB
// per-asset limit, so it cannot be).

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import worker from "../index.js";

function makeKV() {
  const store = new Map();
  return {
    async get(key) { return store.get(key) ?? null; },
    async put(key, value) { store.set(key, value); },
    async delete(key) { store.delete(key); },
  };
}

function envWith(files) {
  return {
    ASSETS: {
      fetch: async (reqOrUrl) => {
        const url = typeof reqOrUrl === "string" ? reqOrUrl : reqOrUrl.url;
        const path = new URL(url).pathname;
        return files.has(path)
          ? new Response(files.get(path), { status: 200 })
          : new Response("<html>404</html>", { status: 404 });
      },
    },
    CHAT_KV: makeKV(),
  };
}

const text = JSON.stringify({ pages: [{ text: "é✓".repeat(20) }] });
const bytes = new TextEncoder().encode(text);
const a = bytes.slice(0, 11);
const b = bytes.slice(11);
const chunked = new Map([
  ["/data/pages-cleaned.json.chunks.json", JSON.stringify({
    name: "pages-cleaned.json",
    size: bytes.length,
    parts: [
      { path: "pages-cleaned.json.part-000.json", size: a.length },
      { path: "pages-cleaned.json.part-001.json", size: b.length },
    ],
  })],
  ["/data/pages-cleaned.json.part-000.json", a],
  ["/data/pages-cleaned.json.part-001.json", b],
]);

describe("chunked /data assets", () => {
  test("GET of a chunked asset's public URL returns the reassembled bytes", async () => {
    const res = await worker.fetch(
      new Request("https://pursueindex.com/data/pages-cleaned.json"), envWith(chunked),
    );
    assert.equal(res.status, 200);
    assert.match(res.headers.get("Content-Type"), /application\/json/);
    assert.match(res.headers.get("Cache-Control"), /max-age=3600/);
    assert.equal(await res.text(), text);
  });

  test("HEAD reports the size without a body", async () => {
    const res = await worker.fetch(
      new Request("https://pursueindex.com/data/pages-cleaned.json", { method: "HEAD" }),
      envWith(chunked),
    );
    assert.equal(res.status, 200);
    assert.equal(res.headers.get("Content-Length"), String(bytes.length));
  });

  test("a /data path with no asset and no manifest stays a 404", async () => {
    const res = await worker.fetch(
      new Request("https://pursueindex.com/data/nope.json"), envWith(chunked),
    );
    assert.equal(res.status, 404);
  });

  test("an asset served whole is passed through untouched", async () => {
    const files = new Map([["/data/pages.json", "[1]"]]);
    const res = await worker.fetch(new Request("https://pursueindex.com/data/pages.json"), envWith(files));
    assert.equal(await res.text(), "[1]");
  });
});
