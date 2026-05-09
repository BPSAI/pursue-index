// Tests for snippet extraction and Voyage query embedding.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { makeSnippet, embedQuery } from "../retrieve.js";

describe("makeSnippet", () => {
  test("returns trimmed text when shorter than maxChars", () => {
    const out = makeSnippet("hello world", "world", 100);
    assert.equal(out, "hello world");
  });

  test("centers around the first matched query term", () => {
    const text = "a".repeat(200) + " roswell incident " + "b".repeat(200);
    const out = makeSnippet(text, "Roswell", 100);
    assert.ok(out.includes("roswell"));
    // Should be ~maxChars long, plus the ellipsis prefix/suffix.
    assert.ok(out.length <= 100 + 4);
  });

  test("falls back to head of text when no match found", () => {
    const text = "a".repeat(200);
    const out = makeSnippet(text, "no-match-here", 50);
    assert.ok(out.startsWith("a".repeat(50)));
    assert.ok(out.endsWith("…"));
  });

  test("handles empty text gracefully", () => {
    assert.equal(makeSnippet("", "anything"), "");
  });
});

describe("embedQuery", () => {
  test("calls voyage with correct input_type=query and model", async () => {
    let captured = null;
    const fakeFetch = async (url, init) => {
      captured = { url, init };
      return new Response(
        JSON.stringify({
          data: [{ embedding: [0.1, 0.2, 0.3] }],
          usage: { total_tokens: 7 },
        }),
        { status: 200 },
      );
    };
    const v = await embedQuery("roswell", "test-key", fakeFetch);
    assert.ok(v instanceof Float32Array);
    assert.equal(v.length, 3);
    const body = JSON.parse(captured.init.body);
    assert.equal(body.model, "voyage-3");
    assert.equal(body.input_type, "query");
    assert.deepEqual(body.input, ["roswell"]);
    assert.equal(captured.init.headers.Authorization, "Bearer test-key");
  });

  test("throws on missing API key", async () => {
    await assert.rejects(() => embedQuery("q", "", async () => {}));
  });

  test("throws on voyage error response", async () => {
    const fakeFetch = async () =>
      new Response("rate limited", { status: 429 });
    await assert.rejects(() => embedQuery("q", "k", fakeFetch), /429/);
  });

  test("throws if response shape is unexpected", async () => {
    const fakeFetch = async () =>
      new Response(JSON.stringify({ wrong: "shape" }), { status: 200 });
    await assert.rejects(() => embedQuery("q", "k", fakeFetch), /embedding/);
  });
});
