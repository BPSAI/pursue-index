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

  const body = new ReadableStream({
    start(c) {
      const enc = new TextEncoder();
      for (const e of events) c.enqueue(enc.encode(e));
      c.error(error);
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}
