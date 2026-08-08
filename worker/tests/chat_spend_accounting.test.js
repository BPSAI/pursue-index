// Spend accounting when a chat stream does not finish.
//
// The upstream Anthropic call is billed the moment it is answered, not when
// its stream drains. A reader that rejects part-way — a reset connection, a
// timeout, a client that navigated away — must therefore still leave a
// charge behind: an unfinished stream is not a free call. These tests drive
// a stream whose reader rejects after a couple of chunks and assert the
// daily spend counter moved anyway.

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { handleChat } from "../chat.js";
import { pipeAnthropicSSE } from "../chat_sse.js";
import { _resetCaches } from "../retrieve.js";
import { anthropicSSEResponse } from "./fixtures/anthropic_sse.js";
import { anthropicSSETruncatedResponse } from "./fixtures/anthropic_sse_truncated.js";

function makeKV() {
  const store = new Map();
  return {
    _store: store,
    async get(key, type) {
      const raw = store.get(key);
      if (raw == null) return null;
      return type === "json" ? JSON.parse(raw) : raw;
    },
    async put(key, value) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

function makeAssetsEnv() {
  const u16 = new Uint16Array([floatToHalf(1), floatToHalf(0), floatToHalf(0)]);
  const indexJson = { model_id: "voyage-3", dim: 3, n: 1, pages: [["card-a", 1]] };
  const pagesArr = [
    {
      id: "card-a-p1",
      card_id: "card-a",
      page: 1,
      title: "Test card",
      text: "The quick brown fox jumped over the lazy dog. Roswell incident details.",
    },
  ];
  return {
    ASSETS: {
      fetch: async (urlOrReq) => {
        const url = typeof urlOrReq === "string" ? urlOrReq : urlOrReq.url;
        if (url.endsWith("/data/embeddings.bin")) return new Response(u16.buffer, { status: 200 });
        if (url.endsWith("/data/embed_index.json"))
          return new Response(JSON.stringify(indexJson), { status: 200 });
        if (url.endsWith("/data/pages.json"))
          return new Response(JSON.stringify(pagesArr), { status: 200 });
        return new Response("not found", { status: 404 });
      },
    },
  };
}

function floatToHalf(f) {
  if (f === 0) return 0;
  const sign = f < 0 ? 1 : 0;
  const a = Math.abs(f);
  const e = Math.floor(Math.log2(a));
  const exp = e + 15;
  const frac = Math.round((a / Math.pow(2, e) - 1) * 1024);
  return (sign << 15) | (exp << 10) | (frac & 0x3ff);
}

function makeChatRequest(ip = "5.5.5.5") {
  return new Request("https://x/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": ip },
    body: JSON.stringify({ query: "Tell me about Roswell" }),
  });
}

function collectingController() {
  return {
    frames: [],
    enqueue(x) {
      this.frames.push(x);
    },
    close() {},
  };
}

/** Capture console output for the duration of `fn`. */
async function captureLogs(fn) {
  const lines = { log: [], warn: [], error: [] };
  const orig = { log: console.log, warn: console.warn, error: console.error };
  for (const level of ["log", "warn", "error"]) {
    console[level] = (...args) => lines[level].push(args.join(" "));
  }
  try {
    return { result: await fn(), lines };
  } finally {
    Object.assign(console, orig);
  }
}

function spentUsd(kv) {
  const key = [...kv._store.keys()].find((k) => k.startsWith("spend:"));
  return key ? parseFloat(kv._store.get(key)) : 0;
}

beforeEach(() => _resetCaches());

describe("pipeAnthropicSSE when the stream does not finish", () => {
  test("calls the abort callback and lets the error propagate", async () => {
    const res = anthropicSSETruncatedResponse("Roswell appears in", {
      chunksBeforeFailure: 2,
    });
    let aborted = null;
    let thrown = null;
    try {
      await pipeAnthropicSSE(
        collectingController(),
        res.body,
        async () => {
          throw new Error("onDone must not run for an unfinished stream");
        },
        async (info) => {
          aborted = info;
        },
      );
    } catch (err) {
      thrown = err;
    }
    assert.ok(thrown, "the read failure must still propagate to the caller");
    assert.ok(aborted, "the abort callback must run");
    assert.ok(aborted.error, "the abort callback is told what went wrong");
  });

  test("a stream that completes normally does NOT call the abort callback", async () => {
    const res = anthropicSSEResponse("Roswell appears in [card-a:1].");
    let aborted = false;
    let done = null;
    await pipeAnthropicSSE(
      collectingController(),
      res.body,
      async (d) => {
        done = d;
      },
      async () => {
        aborted = true;
      },
    );
    assert.equal(aborted, false);
    assert.equal(done.usageParsed, true);
  });
});

describe("handleChat spend accounting", () => {
  test("a stream that fails mid-read still records spend", async () => {
    const kv = makeKV();
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () =>
        anthropicSSETruncatedResponse("Roswell appears in", { chunksBeforeFailure: 2 }),
    };
    const { lines } = await captureLogs(async () => {
      const r = await handleChat(makeChatRequest(), env, opts);
      await r.text();
    });
    // The call was billed upstream, so the daily counter must have moved.
    assert.ok(spentUsd(kv) > 0, "spend was not recorded for an unfinished stream");
    // …and the event has to be observable, not inferred from the bill.
    assert.ok(
      lines.warn.some((l) => l.includes("[chat]")),
      "an unfinished-stream charge must be logged",
    );
  });

  test("a completed stream records spend exactly once", async () => {
    const kv = makeKV();
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => anthropicSSEResponse("Roswell appears in [card-a:1].", {
        inputTokens: 1000,
        outputTokens: 500,
      }),
    };
    const r = await handleChat(makeChatRequest("5.5.5.6"), env, opts);
    await r.text();
    // 1000 in @ $3/Mtok + 500 out @ $15/Mtok = $0.0105 — the metered cost,
    // not the much larger unfinished-stream estimate.
    assert.ok(Math.abs(spentUsd(kv) - 0.0105) < 1e-9, `got ${spentUsd(kv)}`);
  });

  test("an unbound CHAT_KV is warned about, not silently skipped", async () => {
    const env = {
      ...makeAssetsEnv(),
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => anthropicSSEResponse("Roswell appears in [card-a:1]."),
    };
    const { lines } = await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.5.7"), env, opts);
      await r.text();
    });
    assert.ok(
      lines.warn.some((l) => l.includes("CHAT_KV")),
      "an unbound CHAT_KV disables rate limiting, the budget cap and spend accounting — say so",
    );
  });
});
