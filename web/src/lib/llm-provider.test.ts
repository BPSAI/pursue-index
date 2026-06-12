// Tests for the BYOK Anthropic SSE parser. The load-bearing case is the
// safety-refusal path (HTTP 200, stop_reason "refusal", empty content) that
// Claude Fable 5's classifiers — and any model's own refusals — can produce:
// without handling it, a refusal renders as a silent blank chat reply.

import { test } from "node:test";
import assert from "node:assert/strict";
import { parseAnthropicSSE, type Chunk } from "./llm-provider.ts";

function sseStream(blocks: string[]): ReadableStream<Uint8Array> {
  const body = blocks.map((b) => b + "\n\n").join("");
  const bytes = new TextEncoder().encode(body);
  return new ReadableStream({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<Chunk[]> {
  const out: Chunk[] = [];
  for await (const c of parseAnthropicSSE(stream)) out.push(c);
  return out;
}

test("parseAnthropicSSE: refusal stop_reason with no text → error chunk", async () => {
  const chunks = await collect(
    sseStream([
      `event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":12}}}`,
      `event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"refusal"},"usage":{"output_tokens":0}}`,
      `event: message_stop\ndata: {"type":"message_stop"}`,
    ]),
  );
  const err = chunks.find((c) => c.type === "error");
  assert.ok(err, "expected an error chunk on refusal");
  assert.match((err as { message: string }).message, /refus/i);
  assert.equal(chunks.some((c) => c.type === "text"), false);
  assert.equal(chunks.at(-1)?.type, "done");
});

test("parseAnthropicSSE: normal text stream → text chunks, no error", async () => {
  const chunks = await collect(
    sseStream([
      `event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":12}}}`,
      `event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}`,
      `event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}`,
      `event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}`,
      `event: message_stop\ndata: {"type":"message_stop"}`,
    ]),
  );
  assert.equal(
    chunks.filter((c) => c.type === "text").map((c) => (c as { delta: string }).delta).join(""),
    "Hello world",
  );
  assert.equal(chunks.some((c) => c.type === "error"), false);
  const done = chunks.at(-1);
  assert.equal(done?.type, "done");
  assert.equal((done as { usage?: { output_tokens?: number } }).usage?.output_tokens, 2);
});

test("parseAnthropicSSE: refusal but text already streamed → no spurious error", async () => {
  // A mid-stream refusal that already emitted text shouldn't double-report;
  // the streamed partial stands and we don't inject the refusal message.
  const chunks = await collect(
    sseStream([
      `event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}`,
      `event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"refusal"},"usage":{"output_tokens":1}}`,
    ]),
  );
  assert.equal(chunks.some((c) => c.type === "error"), false);
  assert.equal(chunks.some((c) => c.type === "text"), true);
});
