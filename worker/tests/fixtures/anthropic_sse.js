// Fixture: Anthropic Messages streaming (SSE) response.
//
// Provenance
// ----------
// Shape source : Anthropic Messages API, streaming mode
//                (POST https://api.anthropic.com/v1/messages, stream: true)
// API version  : anthropic-version: 2023-06-01
// Event order  : message_start (carries message.usage.input_tokens),
//                content_block_start / _delta / _stop,
//                message_delta (carries usage.output_tokens), message_stop
// Captured     : hand-authored against the documented 2023-06-01 streaming
//                schema. NOT captured from a live wire dump — the values are
//                synthetic. Last reconciled against the docs: 2026-08-08.
//
// The worker's dollar accounting depends on TWO fields living exactly here:
//   message_start .message.usage.input_tokens
//   message_delta .usage.output_tokens
// (see worker/chat_sse.js). If a future API version moves either field, the
// parser reads {0,0} and — before T47.12 — cost accounting silently charged
// $0, so the daily cap never tripped. `anthropicSSEMovedUsageResponse()`
// below models exactly that drift so the fail-closed test can prove the cap
// still engages when the shape moves out from under the parser.

export const ANTHROPIC_SSE_PROVENANCE = {
  endpoint: "https://api.anthropic.com/v1/messages",
  api_version: "2023-06-01",
  stream: true,
  captured: "2026-08-08",
  capture_method: "hand-authored against documented 2023-06-01 schema",
  usage_fields: {
    input_tokens: "message_start.message.usage.input_tokens",
    output_tokens: "message_delta.usage.output_tokens",
  },
};

function sseResponseFromEvents(events) {
  const body = new ReadableStream({
    start(c) {
      const enc = new TextEncoder();
      for (const e of events) c.enqueue(enc.encode(e));
      c.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/**
 * Canonical, well-formed streaming response — usage lives in the documented
 * places the parser reads (see ANTHROPIC_SSE_PROVENANCE.usage_fields).
 */
export function anthropicSSEResponse(
  text,
  { inputTokens = 100, outputTokens = 50 } = {},
) {
  const events = [
    `event: message_start\ndata: ${JSON.stringify({ type: "message_start", message: { id: "m1", model: "claude-sonnet-4-6", usage: { input_tokens: inputTokens, output_tokens: 0 } } })}\n\n`,
    `event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`,
    `event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text } })}\n\n`,
    `event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`,
    `event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", usage: { output_tokens: outputTokens } })}\n\n`,
    `event: message_stop\ndata: ${JSON.stringify({ type: "message_stop" })}\n\n`,
  ];
  return sseResponseFromEvents(events);
}

/**
 * Same well-formed stream, but the usage fields have MOVED to a location the
 * current parser does not read — models a future Anthropic API-shape drift.
 * input/output token counts now live under `.usage.tokens.{input,output}`
 * instead of `.usage.{input_tokens,output_tokens}`. The parser sees {0,0};
 * fail-closed accounting must treat that as a fault, never as a free call.
 */
export function anthropicSSEMovedUsageResponse(text) {
  const events = [
    `event: message_start\ndata: ${JSON.stringify({ type: "message_start", message: { id: "m1", model: "claude-sonnet-4-6", usage: { tokens: { input: 100 } } } })}\n\n`,
    `event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`,
    `event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text } })}\n\n`,
    `event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`,
    `event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", usage: { tokens: { output: 50 } } })}\n\n`,
    `event: message_stop\ndata: ${JSON.stringify({ type: "message_stop" })}\n\n`,
  ];
  return sseResponseFromEvents(events);
}
