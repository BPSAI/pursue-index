// Fixture: an Anthropic streaming response whose body fails mid-read.
//
// Models the real failure the worker has to survive: the API call was made
// and billed, some SSE chunks arrived, and then the read errored — a reset
// connection, an upstream timeout, or a client that went away. The stream
// never reaches `message_delta`, so no usage counts are available and the
// normal completion callback never runs.
//
// Shape source: same 2023-06-01 streaming schema as anthropic_sse.js; the
// event prefix here is a truncation of that canonical sequence.

export function anthropicSSETruncatedResponse(
  text,
  { chunksBeforeFailure = 2, error = new TypeError("network connection lost") } = {},
) {
  const events = [
    `event: message_start\ndata: ${JSON.stringify({ type: "message_start", message: { id: "m1", model: "claude-sonnet-4-6", usage: { input_tokens: 100, output_tokens: 0 } } })}\n\n`,
    `event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`,
    `event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text } })}\n\n`,
  ].slice(0, chunksBeforeFailure);

  return sseStreamThenError(events, error);
}

/**
 * Deliver `events` one read at a time, then fail.
 *
 * `pull` rather than a loop in `start`: erroring a stream discards whatever
 * is still queued, so events enqueued up front would never reach the reader
 * and the fixture would model a stream that failed before saying anything.
 */
function sseStreamThenError(events, error) {
  const enc = new TextEncoder();
  let i = 0;
  const body = new ReadableStream({
    pull(c) {
      if (i < events.length) {
        c.enqueue(enc.encode(events[i++]));
        return;
      }
      c.error(error);
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/**
 * A stream that reported its full usage and THEN failed.
 *
 * Anthropic sends `message_delta` (carrying output_tokens) before
 * `message_stop`, so a connection that drops in that last gap leaves the
 * worker holding real, metered token counts for a call it never saw finish.
 * The completion callback still never runs — accounting happens on the abort
 * path, which is why that path cannot simply discard the usage it was given.
 */
export function anthropicSSEUsageThenFailureResponse(
  text,
  {
    inputTokens = 100_000,
    outputTokens = 1_000,
    error = new TypeError("network connection lost"),
  } = {},
) {
  const events = [
    `event: message_start\ndata: ${JSON.stringify({ type: "message_start", message: { id: "m1", model: "claude-sonnet-4-6", usage: { input_tokens: inputTokens, output_tokens: 0 } } })}\n\n`,
    `event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`,
    `event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text } })}\n\n`,
    `event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`,
    `event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", usage: { output_tokens: outputTokens } })}\n\n`,
  ];
  return sseStreamThenError(events, error);
}
