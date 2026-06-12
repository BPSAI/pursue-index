// LLM provider abstraction.
//
// The chat surface speaks a single Chunk-stream interface so that
// swapping the LLM backend (server-funded Anthropic, BYOK Anthropic,
// future OpenAI/Ollama) is a one-file change. Both the anonymous tier
// and the BYOK tier go through /api/retrieve for context — only the
// LLM call differs.
//
// Wire format (matches worker/chat_sse.js for the server provider):
//   {type: "citations", passages: [...]}    — sent first
//   {type: "text", delta: string}            — streaming text deltas
//   {type: "done", usage?, abstained?}       — stream complete
//   {type: "error", message: string}         — terminal error
//
// `done` always fires (even after error) so consumers can flush UI
// state in a single place.

export interface Citation {
  card_id: string;
  page: number;
  title: string;
  snippet: string;
  score: number;
}

export interface TokenUsage {
  input_tokens?: number;
  output_tokens?: number;
}

export type Chunk =
  | { type: "citations"; passages: Citation[] }
  | { type: "text"; delta: string }
  | { type: "done"; usage?: TokenUsage; cached?: boolean; abstained?: boolean }
  | { type: "error"; message: string };

export interface StreamOpts {
  model?: string;
  abortSignal?: AbortSignal;
}

export interface LLMProvider {
  readonly name: string;
  readonly model: string;
  /** True iff this provider talks to Anthropic from the browser using a user-supplied key. */
  readonly isBYOK: boolean;
  stream(query: string, opts?: StreamOpts): AsyncIterable<Chunk>;
}

// ---------------------------------------------------------------------------
// SSE parser shared by the server provider and (when streaming) BYOK.
// ---------------------------------------------------------------------------

/**
 * Read a Response body as our Chunk stream. The wire format is the one
 * defined in worker/chat_sse.js: blocks of `event: NAME\ndata: JSON\n\n`.
 */
export async function* readChunkStream(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncIterable<Chunk> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const evt = parseSSEBlock(block);
        if (!evt) continue;
        const chunk = mapServerEventToChunk(evt);
        if (chunk) yield chunk;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

interface SSEEvent {
  event: string;
  data: any;
}

function parseSSEBlock(block: string): SSEEvent | null {
  let event = "message";
  let data: any = null;
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

function mapServerEventToChunk(evt: SSEEvent): Chunk | null {
  switch (evt.event) {
    case "citations":
      return { type: "citations", passages: evt.data as Citation[] };
    case "text":
      return { type: "text", delta: (evt.data as any).delta || "" };
    case "done":
      return {
        type: "done",
        usage: (evt.data as any).usage,
        cached: !!(evt.data as any).cached,
        abstained: !!(evt.data as any).abstained,
      };
    case "error":
      return { type: "error", message: (evt.data as any).message || "error" };
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Server-funded provider (anonymous tier, default).
// ---------------------------------------------------------------------------

export class AnthropicServerProvider implements LLMProvider {
  readonly name = "anonymous (server)";
  readonly model = "claude-sonnet-4-6";
  readonly isBYOK = false;

  async *stream(query: string, opts: StreamOpts = {}): AsyncIterable<Chunk> {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      signal: opts.abortSignal,
    });
    if (!res.ok) {
      let msg = `chat request failed: ${res.status}`;
      try {
        const j = await res.json();
        if (j?.error) msg = j.error;
      } catch {
        /* ignore — non-JSON body */
      }
      yield { type: "error", message: msg };
      yield { type: "done" };
      return;
    }
    if (!res.body) {
      yield { type: "error", message: "empty response body" };
      yield { type: "done" };
      return;
    }
    yield* readChunkStream(res.body, opts.abortSignal);
  }
}

// ---------------------------------------------------------------------------
// BYOK provider — talks to Anthropic from the browser with the user's key.
//
// Retrieval still goes through our Worker (we don't ship 8 MB of vectors
// to the browser). The LLM call goes direct so the user's key never
// touches our origin.
// ---------------------------------------------------------------------------

const ANTHROPIC_DIRECT_URL = "https://api.anthropic.com/v1/messages";

export class AnthropicBYOKProvider implements LLMProvider {
  readonly name = "BYOK (Anthropic)";
  readonly isBYOK = true;
  readonly model: string;
  private apiKey: string;

  constructor(apiKey: string, model = "claude-sonnet-4-6") {
    if (!apiKey) throw new Error("AnthropicBYOKProvider requires an API key");
    if (!apiKey.startsWith("sk-ant-")) {
      throw new Error("Anthropic key must start with sk-ant-");
    }
    this.apiKey = apiKey;
    this.model = model;
  }

  async *stream(query: string, opts: StreamOpts = {}): AsyncIterable<Chunk> {
    // 1) Retrieval still via Worker (cookie-gated, no PII leaked).
    let passages: Citation[] = [];
    try {
      const r = await fetch("/api/retrieve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, k: 8 }),
        signal: opts.abortSignal,
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        yield { type: "error", message: j?.error || `retrieve ${r.status}` };
        yield { type: "done" };
        return;
      }
      const data = await r.json();
      passages = (data.passages || []).map((p: any) => ({
        card_id: p.card_id,
        page: p.page,
        title: p.title,
        snippet: p.snippet,
        score: p.score,
      }));
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      yield { type: "error", message: String(e?.message || e) };
      yield { type: "done" };
      return;
    }
    yield { type: "citations", passages };

    if (passages.length === 0) {
      yield {
        type: "text",
        delta: "The documents in this corpus do not address that.",
      };
      yield { type: "done", abstained: true };
      return;
    }

    // 2) LLM call direct to Anthropic.
    yield* this.streamFromAnthropic(query, passages, opts);
  }

  private async *streamFromAnthropic(
    query: string,
    passages: Citation[],
    opts: StreamOpts,
  ): AsyncIterable<Chunk> {
    const { system, user } = await buildBYOKPrompt(query, passages);
    let res: Response;
    try {
      res = await fetch(ANTHROPIC_DIRECT_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": this.apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: opts.model || this.model,
          max_tokens: 1024,
          stream: true,
          system,
          messages: [{ role: "user", content: user }],
        }),
        signal: opts.abortSignal,
      });
    } catch (e: any) {
      if (e?.name === "AbortError") return;
      yield { type: "error", message: String(e?.message || e) };
      yield { type: "done" };
      return;
    }
    if (!res.ok || !res.body) {
      const body = await res.text().catch(() => "");
      yield {
        type: "error",
        message: `Anthropic ${res.status}: ${body.slice(0, 200)}`,
      };
      yield { type: "done" };
      return;
    }
    yield* parseAnthropicSSE(res.body, opts.abortSignal);
  }
}

/**
 * Parse Anthropic's native SSE stream into our Chunk format. Used by
 * the BYOK provider; the server provider relies on the Worker doing
 * this same translation.
 */
export async function* parseAnthropicSSE(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncIterable<Chunk> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let usage: TokenUsage = {};
  // Track the terminal stop_reason + whether any text streamed, so a
  // safety refusal (HTTP 200, stop_reason "refusal", empty/partial content —
  // Claude Fable 5's classifiers, and any model's own refusals) surfaces a
  // message instead of a silent blank reply.
  let stopReason: string | undefined;
  let emittedText = false;
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
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
          emittedText = true;
          yield { type: "text", delta: evt.data.delta.text as string };
        } else if (evt.event === "message_start" && evt.data?.message?.usage) {
          usage.input_tokens = evt.data.message.usage.input_tokens;
        } else if (evt.event === "message_delta") {
          if (evt.data?.delta?.stop_reason) {
            stopReason = evt.data.delta.stop_reason as string;
          }
          if (evt.data?.usage?.output_tokens) {
            usage.output_tokens = evt.data.usage.output_tokens;
          }
        }
      }
    }
    if (stopReason === "refusal" && !emittedText) {
      yield {
        type: "error",
        message:
          "The model declined to answer this request (safety refusal). Try rephrasing, or pick a different model in Settings.",
      };
    }
  } finally {
    reader.releaseLock();
    yield { type: "done", usage };
  }
}

// The BYOK prompt mirrors the one on the Worker side; we duplicate the
// constant text rather than reach over the network for it. If we ever
// make the server prompt configurable, expose it via /api/prompt.
async function buildBYOKPrompt(query: string, passages: Citation[]) {
  const { BYOK_SYSTEM_PROMPT, buildBYOKUser } = await import(
    "./byok-prompt.ts"
  );
  return { system: BYOK_SYSTEM_PROMPT, user: buildBYOKUser(query, passages) };
}

// ---------------------------------------------------------------------------
// Stub providers (post-launch).
// ---------------------------------------------------------------------------

export class OpenAIBYOKProvider implements LLMProvider {
  readonly name = "BYOK (OpenAI)";
  readonly model = "gpt-4o";
  readonly isBYOK = true;
  // eslint-disable-next-line require-yield
  async *stream(): AsyncIterable<Chunk> {
    throw new Error("OpenAI BYOK not yet supported");
  }
}
