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
  checkAndIncrementRate,
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

  // Step 2: per-IP rate limit.
  if (kv) {
    const rate = await checkAndIncrementRate(kv, ip, day);
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

  // SSE response body — controller drives the writes.
  const stream = new ReadableStream({
    async start(controller) {
      try {
        // Step 5: canned abstention if retrieval is empty.
        if (passages.length === 0) {
          streamAbstention(controller, query);
          controller.close();
          return;
        }
        // Send citations event up-front so the UI can render the sidebar.
        const citations = passages.map((p) => ({
          card_id: p.card_id,
          page: p.page,
          title: p.title,
          snippet: p.snippet,
          score: p.score,
        }));
        controller.enqueue(sseFrame("citations", citations));

        // Step 6: cache lookup.
        const ck = cacheKey(query, passages);
        if (kv) {
          const cached = await readCache(kv, ck);
          if (cached) {
            replayCachedAsSSE(controller, { ...cached, citations });
            controller.close();
            return;
          }
        }

        // Step 7: live Anthropic streaming call.
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
          const t = await apiRes.text();
          controller.enqueue(
            sseFrame("error", {
              message: `anthropic ${apiRes.status}: ${t.slice(0, 200)}`,
            }),
          );
          controller.close();
          return;
        }
        await pipeAnthropicSSE(controller, apiRes.body, async ({ usage, fullText }) => {
          // Record spend + write cache entry.
          if (kv) {
            const usd = costUsd(usage);
            await recordSpend(kv, day, usd);
            await writeCache(kv, ck, {
              text: fullText,
              usage,
              model: DEFAULT_MODEL,
            });
          }
        });
        controller.close();
      } catch (err) {
        console.error("chat stream error", err);
        controller.enqueue(
          sseFrame("error", { message: String(err.message || err) }),
        );
        controller.close();
      }
    },
  });

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

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
