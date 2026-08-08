// SSE plumbing for /api/chat.
//
// We translate Anthropic's content-block-delta SSE format into a leaner
// event stream the browser-side provider abstraction understands:
//
//   event: citations\ndata: [{...}]    — passages used; sent up-front
//   event: text\ndata: {"delta": "..."} — streaming text deltas
//   event: done\ndata: {"usage": ...}   — usage stats + close
//   event: error\ndata: {"message"...}  — error termination
//
// Keeping the wire format ours (not raw Anthropic) means we can swap
// providers later without breaking the browser parser.

const ENC = new TextEncoder();

export function sseFrame(event, data) {
  return ENC.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

/**
 * Pipe an Anthropic SSE response body through to the client SSE stream,
 * extracting text deltas and usage info. Calls
 * `onDone({usage, fullText, usageParsed})` once the upstream stream
 * completes (used to record cache + spend).
 *
 * `usageParsed` is the fail-closed signal for cost accounting: a genuinely
 * completed Anthropic call always reports positive input AND output token
 * counts. If either is still zero once the stream drains, the upstream usage
 * shape has moved (or was absent) and the caller must NOT read that as a
 * real, free ($0) call — otherwise a silent shape change lets the daily
 * spend cap run unbounded. See worker/chat.js's onDone callback.
 *
 * `onAbort({error, usage, fullText})` runs when the read fails part-way, in
 * which case `onDone` never runs. The upstream call was already billed by
 * then, so this is where the caller charges for it; the read error is
 * re-thrown afterwards so the client still sees a failed request.
 */
export async function pipeAnthropicSSE(controller, anthropicBody, onDone, onAbort) {
  const reader = anthropicBody.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let usage = { input_tokens: 0, output_tokens: 0 };
  let fullText = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const evt = parseSSEBlock(block);
        if (!evt) continue;
        if (evt.event === "content_block_delta" && evt.data?.delta?.text) {
          const delta = evt.data.delta.text;
          fullText += delta;
          controller.enqueue(sseFrame("text", { delta }));
        } else if (evt.event === "message_start" && evt.data?.message?.usage) {
          usage.input_tokens = evt.data.message.usage.input_tokens || 0;
        } else if (evt.event === "message_delta" && evt.data?.usage) {
          if (evt.data.usage.output_tokens) {
            usage.output_tokens = evt.data.usage.output_tokens;
          }
        }
      }
    }
  } catch (err) {
    // The call was billed whether or not its stream drained, so accounting
    // runs here before the error propagates. A failure inside the callback
    // must not replace the read error the caller needs to see.
    if (onAbort) {
      try {
        await onAbort({ error: err, usage, fullText });
      } catch (accountingErr) {
        console.error("[chat] spend accounting failed after a read error", accountingErr);
      }
    }
    throw err;
  }
  // Fail-closed accounting signal — see the doc comment above. Both counts
  // must be positive for the usage to be trusted; anything else is a fault.
  const usageParsed = usage.input_tokens > 0 && usage.output_tokens > 0;
  controller.enqueue(sseFrame("done", { usage }));
  if (onDone) {
    // The client already has its answer and its done frame. Accounting runs
    // after both, so a failure here is a bookkeeping loss to log — not a
    // failed request. Letting it throw would surface an error frame after
    // the done frame to a client whose answer arrived intact, and would
    // bury the real cause under the caller's generic stream-error path.
    try {
      await onDone({ usage, fullText, usageParsed });
    } catch (accountingErr) {
      console.error(
        "[chat] spend accounting failed after a completed stream — the call was billed but not recorded",
        accountingErr,
      );
    }
  }
}

function parseSSEBlock(block) {
  let event = "message";
  let data = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) {
      const raw = line.slice(5).trim();
      try {
        data = JSON.parse(raw);
      } catch {
        data = raw;
      }
    }
  }
  return data == null ? null : { event, data };
}

/**
 * Replay a cached chat as a fresh SSE stream so the client code path
 * is identical between cold and warm cache hits.
 */
export function replayCachedAsSSE(controller, cached) {
  if (cached.citations) {
    controller.enqueue(sseFrame("citations", cached.citations));
  }
  // Send the full text in one chunk; the browser will render instantly.
  if (cached.text) {
    controller.enqueue(sseFrame("text", { delta: cached.text }));
  }
  controller.enqueue(sseFrame("done", { usage: cached.usage || {}, cached: true }));
}

/**
 * Send an in-stream abstention message (no Anthropic call) when retrieval
 * comes up empty. The model would also abstain — but skipping the call
 * saves both spend and latency.
 */
export function streamAbstention(controller, query) {
  const text = "The documents in this corpus do not address that.";
  controller.enqueue(sseFrame("citations", []));
  controller.enqueue(sseFrame("text", { delta: text }));
  controller.enqueue(sseFrame("done", { usage: {}, abstained: true }));
}
