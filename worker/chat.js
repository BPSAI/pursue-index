// /api/chat — RAG over the corpus, streamed Anthropic response.
//
// Order of operations:
//   1. Method + body validation
//   2. Per-IP rate limit (KV) — refuse with 429 + BYOK CTA on 6th call
//   3. Daily $ budget cap (KV) — refuse with 503 + BYOK CTA when exhausted
//   4. Retrieve top-k passages via worker/retrieve.js
//   5. If no passages clear the threshold → stream the canned abstention
//      (saves both latency and money; the model would say the same thing)
//   6. Cache lookup keyed on (query, sorted card_id:page list)
//      → if hit, replay as SSE in the same wire format as a fresh stream
//   7. Otherwise: build prompt, call Anthropic stream, pipe through;
//      on completion record spend + write cache entry.
//
// All external dependencies (Anthropic, Voyage, KV, ASSETS) are passed
// through the env or an opts object so the test suite can mock them.

import { retrievePassages } from "./retrieve.js";
import { buildSystemPrompt, buildUserPrompt } from "./chat_prompt.js";
import {
  checkRate,
  incrementRate,
  cacheKey,
  readCache,
  writeCache,
  checkBudget,
  recordSpend,
  utcDay,
} from "./chat_kv.js";
import {
  sseFrame,
  pipeAnthropicSSE,
  replayCachedAsSSE,
  streamAbstention,
} from "./chat_sse.js";

const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const DEFAULT_MODEL = "claude-sonnet-4-6";
const MAX_TOKENS = 1024;

// Anthropic Sonnet 4.6 list price (USD per million tokens).
const PRICE_INPUT = 3.0;
const PRICE_OUTPUT = 15.0;

// Fail-closed fallback: what to charge when the upstream usage report can't
// be parsed. We must NEVER account an unparseable/absent usage as $0 — that
// is exactly the failure that lets a moved API shape run the daily cap
// unbounded on a public endpoint. The estimate is a deliberate upper bound on
// a single call: the largest output the model can emit (MAX_TOKENS) plus a
// generous input allowance for the system prompt + up to 8 retrieved
// passages. Erring high protects the cap; a real call costs less.
const FALLBACK_INPUT_TOKENS = 20_000;
const FALLBACK_OUTPUT_TOKENS = MAX_TOKENS;

export async function handleChat(request, env, opts = {}) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "method not allowed" }, 405);
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid JSON body" }, 400);
  }
  const query = (body?.query || "").toString().trim();
  if (!query) return jsonResponse({ error: "query required" }, 400);
  if (query.length > 1000) {
    return jsonResponse({ error: "query too long (max 1000 chars)" }, 400);
  }

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const day = utcDay();
  const kv = env.CHAT_KV;
  if (!kv) {
    // Every accounting call below is a no-op without the namespace, so an
    // unbound binding means this request is rate-limited by nothing, capped
    // by nothing, and billed to no counter. Say so rather than skipping
    // silently — a misconfigured deploy otherwise looks exactly like a
    // healthy one until the invoice arrives.
    console.warn(
      "[chat] CHAT_KV is not bound — rate limiting, the daily budget cap and " +
        "spend accounting are all disabled for this request",
    );
  }

  // Step 2: per-IP rate limit — read-only check, no increment yet.
  // Abstention shortcuts and cache hits skip the increment entirely
  // because they don't spend Anthropic tokens; only an actual upstream
  // call ticks the counter forward (see the pipeAnthropicSSE callback).
  if (kv) {
    const rate = await checkRate(kv, ip, day);
    if (!rate.allowed) {
      return jsonResponse(
        {
          error:
            "Daily rate limit reached for this IP. Bring your own Anthropic key (BYOK) in Settings to keep chatting.",
          rate_limit: rate.count,
        },
        429,
      );
    }
  }

  // Step 3: daily $ budget.
  if (kv) {
    const budget = await checkBudget(kv, day);
    if (!budget.allowed) {
      return jsonResponse(
        {
          error:
            "We've hit today's high-traffic budget cap. Try again tomorrow, or bring your own Anthropic key (BYOK) in Settings to chat without limits.",
        },
        503,
      );
    }
  }

  // Step 4: retrieval.
  let passages;
  try {
    passages = await retrievePassages(query, 8, env, opts.embedFn);
  } catch (err) {
    console.error("retrieve error", err);
    return jsonResponse(
      { error: "retrieval failed: " + String(err.message || err) },
      502,
    );
  }

  // Step 5: canned abstention if retrieval is empty.
  // Returned as its own SSE response — no rate-counter increment, no
  // Anthropic call, no cache write. Saves both spend and the user's
  // daily quota for genuine off-corpus queries.
  if (passages.length === 0) {
    return abstentionSSEResponse(query);
  }

  const citations = passages.map((p) => ({
    card_id: p.card_id,
    page: p.page,
    title: p.title,
    snippet: p.snippet,
    score: p.score,
  }));

  // Step 6: cache lookup.
  // Cache hits replay the saved answer as a fresh SSE — same wire format
  // as a live stream so the client code path is identical. No rate-counter
  // increment because no Anthropic call.
  const ck = cacheKey(query, passages);
  if (kv) {
    const cached = await readCache(kv, ck);
    if (cached) {
      return cacheReplaySSEResponse({ ...cached, citations });
    }
  }

  // Step 7: we're committed to a real upstream call. Increment the rate
  // counter NOW, in the handler's main flow, before constructing the
  // streaming response — so callers (including tests) can rely on the
  // counter being current the moment handleChat returns. Doing this
  // inside the stream's start() function isn't reliable: Node's stream
  // consumers can race the start function's awaits against the close.
  if (kv) {
    await incrementRate(kv, ip, day);
  }

  return liveAnthropicSSEResponse({
    query,
    passages,
    citations,
    ck,
    kv,
    env,
    opts,
    day,
  });
}

// ---------------------------------------------------------------------------
// Response builders — each returns a 200 SSE Response in the same wire
// format. Splitting them out keeps handleChat's main flow linear and lets
// the rate-counter increment happen synchronously in handleChat itself.
// ---------------------------------------------------------------------------

function abstentionSSEResponse(query) {
  const stream = new ReadableStream({
    start(controller) {
      streamAbstention(controller, query);
      controller.close();
    },
  });
  return sseResponse(stream);
}

function cacheReplaySSEResponse(cached) {
  const stream = new ReadableStream({
    start(controller) {
      replayCachedAsSSE(controller, cached);
      controller.close();
    },
  });
  return sseResponse(stream);
}

function liveAnthropicSSEResponse({ query, passages, citations, ck, kv, env, opts, day }) {
  const stream = new ReadableStream({
    async start(controller) {
      try {
        controller.enqueue(sseFrame("citations", citations));

        const anthropicFetch = opts.anthropicFetch || fetch;
        const sys = buildSystemPrompt();
        const user = buildUserPrompt(query, passages);
        const apiRes = await anthropicFetch(ANTHROPIC_URL, {
          method: "POST",
          headers: anthropicHeaders(env.ANTHROPIC_API_KEY),
          body: JSON.stringify({
            model: DEFAULT_MODEL,
            max_tokens: MAX_TOKENS,
            stream: true,
            system: sys,
            messages: [{ role: "user", content: user }],
          }),
        });
        if (!apiRes.ok) {
          // Log the full body server-side for debugging; do NOT pipe it to
          // the client. Anthropic error responses can include partial-key
          // hints, rate-limit details, and other server context. Client
          // gets a sanitized message keyed only on the upstream status.
          const fullBody = await apiRes.text();
          console.error("anthropic upstream error", apiRes.status, fullBody);
          controller.enqueue(
            sseFrame("error", {
              message: clientErrorMessage(apiRes.status),
              status: apiRes.status,
            }),
          );
          controller.close();
          return;
        }
        await pipeAnthropicSSE(
          controller,
          apiRes.body,
          async (result) => {
            // Stream completed — record the dollar spend and cache the
            // answer. The rate counter was already incremented in
            // handleChat's main flow before this stream was constructed.
            if (!kv) return;
            await recordCompletedSpend({ kv, day, ck, ...result });
          },
          async ({ error, usage }) => {
            // The stream failed part-way. Anthropic billed the call the
            // moment it answered, so it is charged here at the same
            // conservative estimate an unparseable usage block gets —
            // never $0, which would let a run of dropped connections
            // spend past the daily cap without the cap ever tripping.
            if (!kv) return;
            await recordAbortedSpend({ kv, day, error, usage });
          },
        );
        controller.close();
      } catch (err) {
        // Same rule as the upstream-status branch above: the full error is
        // for the log, the client gets the sanitized message. An internal
        // error string can name KV keys, bindings and other server detail
        // that a public endpoint has no business handing to a browser.
        console.error("[chat] stream error", err);
        controller.enqueue(
          sseFrame("error", { message: clientErrorMessage(err?.status) }),
        );
        controller.close();
      }
    },
  });
  return sseResponse(stream);
}

/**
 * The only error text /api/chat ever sends a browser.
 *
 * Keyed on the upstream HTTP status where there is one; everything else —
 * including any error raised inside this worker — collapses to the generic
 * message. Nothing derived from an exception's own text reaches the client.
 */
function clientErrorMessage(status) {
  if (status === 401 || status === 403) {
    return "Upstream LLM provider rejected the request. Try BYOK.";
  }
  if (status === 429) {
    return "Upstream LLM provider is rate-limiting. Try again shortly or use BYOK.";
  }
  if (status) return "Upstream LLM provider returned an error. Try again shortly.";
  return "The answer stream failed. Try again shortly.";
}

/** Charge and cache a stream that drained normally. */
async function recordCompletedSpend({ kv, day, ck, usage, fullText, usageParsed }) {
  // Fail closed: if the upstream usage shape moved (or was absent), charge a
  // conservative estimate rather than $0 so the daily cap still converges
  // instead of silently never tripping.
  const usd = usageParsed ? costUsd(usage) : fallbackCostUsd();
  const { spent } = await recordSpend(kv, day, usd);
  // Make daily accounting observable: a silent zero should be visible in
  // logs, not inferred from a runaway bill.
  console.log(
    "[chat] spend recorded " +
      JSON.stringify({ day, usd, cumulative: spent, usage_parsed: usageParsed, usage }),
  );
  if (!usageParsed) {
    console.warn(
      "[chat] anthropic usage unparseable — charged fallback estimate " +
        JSON.stringify({ day, usd, cumulative: spent, usage }),
    );
  }
  await writeCache(kv, ck, { text: fullText, usage, model: DEFAULT_MODEL });
}

/** Charge a stream that failed before it finished. */
async function recordAbortedSpend({ kv, day, error, usage }) {
  // A stream can fail after Anthropic already reported its token counts —
  // message_delta arrives before message_stop, so a drop in that gap leaves
  // real metered usage behind. Charge whichever is larger: the estimate is a
  // floor for what we could not measure, not a substitute for what we did.
  const usageParsed = usage?.input_tokens > 0 && usage?.output_tokens > 0;
  const usd = usageParsed
    ? Math.max(fallbackCostUsd(), costUsd(usage))
    : fallbackCostUsd();
  const { spent } = await recordSpend(kv, day, usd);
  console.warn(
    "[chat] stream ended before it completed — charged " +
      (usageParsed ? "the greater of metered usage and the estimate " : "the fallback estimate ") +
      JSON.stringify({
        day,
        usd,
        cumulative: spent,
        usage,
        error: String(error?.message || error),
      }),
  );
}

function sseResponse(stream) {
  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

function anthropicHeaders(key) {
  return {
    "Content-Type": "application/json",
    "x-api-key": key || "",
    "anthropic-version": "2023-06-01",
  };
}

function costUsd(usage) {
  const inTok = usage?.input_tokens || 0;
  const outTok = usage?.output_tokens || 0;
  return (inTok * PRICE_INPUT + outTok * PRICE_OUTPUT) / 1_000_000;
}

// Conservative upper-bound charge for a call whose usage couldn't be parsed.
// Non-zero by construction so an unaccountable call still advances the cap.
function fallbackCostUsd() {
  return (
    (FALLBACK_INPUT_TOKENS * PRICE_INPUT +
      FALLBACK_OUTPUT_TOKENS * PRICE_OUTPUT) /
    1_000_000
  );
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
