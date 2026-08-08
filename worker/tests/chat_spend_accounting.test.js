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
import {
  anthropicSSETruncatedResponse,
  anthropicSSEUsageThenFailureResponse,
} from "./fixtures/anthropic_sse_truncated.js";

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

/** A KV whose writes to a chosen key prefix reject, as a real KV can. */
function makeFailingKV(failPrefix) {
  const kv = makeKV();
  const put = kv.put.bind(kv);
  kv.put = async (key, value, opts) => {
    if (key.startsWith(failPrefix)) throw new Error(`KV put failed: ${key}`);
    return put(key, value, opts);
  };
  return kv;
}

/** The SSE event names a client saw, in order. */
function frameEvents(sseText) {
  return [...sseText.matchAll(/^event: (.+)$/gm)].map((m) => m[1]);
}

/** The data payloads of one SSE event name. */
function frameData(sseText, event) {
  const out = [];
  for (const block of sseText.split("\n\n")) {
    const name = /^event: (.+)$/m.exec(block);
    const data = /^data: (.*)$/m.exec(block);
    if (name && data && name[1] === event) out.push(JSON.parse(data[1]));
  }
  return out;
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

  test("a stream that reported usage before failing is charged the metered cost", async () => {
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
        anthropicSSEUsageThenFailureResponse("Roswell appears in", {
          inputTokens: 100_000,
          outputTokens: 1_000,
        }),
    };
    await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.5.8"), env, opts);
      await r.text();
    });
    // 100k in @ $3/Mtok + 1k out @ $15/Mtok = $0.315 — well above the
    // $0.07536 estimate, which is a floor for unknown usage, not a cap.
    assert.ok(Math.abs(spentUsd(kv) - 0.315) < 1e-9, `got ${spentUsd(kv)}`);
  });

  test("a small metered cost on a failed stream is still floored at the estimate", async () => {
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
        anthropicSSEUsageThenFailureResponse("Roswell appears in", {
          inputTokens: 100,
          outputTokens: 50,
        }),
    };
    await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.5.9"), env, opts);
      await r.text();
    });
    // Metered $0.00105, estimate $0.07536: an interrupted stream can have
    // been billed for work whose tokens never reached us, so the estimate
    // holds as the floor.
    assert.ok(Math.abs(spentUsd(kv) - 0.07536) < 1e-9, `got ${spentUsd(kv)}`);
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

// Accounting runs after the client has already been told the stream is
// done. A failure there is a bookkeeping loss to log — it is not a failed
// answer, and it must not be reported to a client whose answer arrived.
describe("accounting failures after the stream completed", () => {
  function envWith(kv) {
    return {
      ...makeAssetsEnv(),
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
  }

  test("a spend-write failure on the success path is logged, not sent to the client", async () => {
    const kv = makeFailingKV("spend:");
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => anthropicSSEResponse("Roswell appears in [card-a:1]."),
    };
    const { result: sse, lines } = await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.6.1"), envWith(kv), opts);
      return await r.text();
    });
    const events = frameEvents(sse);
    assert.ok(events.includes("done"), "the answer completed, so the done frame is owed");
    assert.ok(
      !events.includes("error"),
      `no error frame after done — got ${JSON.stringify(events)}`,
    );
    // Match the specific message, not the prefix: every log this worker
    // writes carries `[chat]`, so a prefix check passes on an unrelated
    // line and would keep passing if the accounting log were dropped.
    assert.ok(
      [...lines.error, ...lines.warn].some((l) =>
        l.includes("spend accounting failed after a completed stream"),
      ),
      "an unrecorded charge on the success path must name itself in the logs",
    );
  });

  test("a spend-write failure on the abort path is logged and the stream still fails", async () => {
    const kv = makeFailingKV("spend:");
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () =>
        anthropicSSETruncatedResponse("Roswell appears in", { chunksBeforeFailure: 2 }),
    };
    const { result: sse, lines } = await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.6.2"), envWith(kv), opts);
      return await r.text();
    });
    assert.ok(
      frameEvents(sse).includes("error"),
      "the read genuinely failed, so the client is told the request failed",
    );
    assert.ok(
      lines.error.some((l) => l.includes("spend accounting failed after a read error")),
      "the lost charge on the abort path must name itself in the logs",
    );
  });

  test("the client-facing error message carries no internal detail", async () => {
    const kv = makeFailingKV("spend:");
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () =>
        anthropicSSETruncatedResponse("Roswell appears in", { chunksBeforeFailure: 2 }),
    };
    const { result: sse, lines } = await captureLogs(async () => {
      const r = await handleChat(makeChatRequest("5.5.6.3"), envWith(kv), opts);
      return await r.text();
    });
    const messages = frameData(sse, "error").map((d) => d.message);
    assert.equal(messages.length, 1);
    for (const needle of ["KV put failed", "spend:", "network connection lost"]) {
      assert.ok(
        !messages[0].includes(needle),
        `client message leaked internal detail (${needle}): ${messages[0]}`,
      );
    }
    assert.ok(messages[0].length > 0, "the client still gets a message it can render");
    // The detail the operator needs stays server-side.
    assert.ok(
      lines.error.some((l) => l.includes("network connection lost")),
      "the underlying error must still be logged in full",
    );
  });
});
