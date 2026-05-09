---
id: chat-interface
type: feature
status: shipped
created: 2026-05-08
shipped: 2026-05-09
shipped_in: [0ed5ef3, 5e05037, c2a5194, 0824df5, 3998b75, 3ed702a, ca34af3, 32d442b, fa34aca]
depends_on: [embed-stage, ui-redesign-alien]
priority: high
---

> **Shipped 2026-05-09.** End-to-end RAG chat with mandatory citations,
> anonymous (server-funded) + BYOK (browser → Anthropic direct) tiers.
>
> **Worker:** `/api/retrieve` parses 8 MB float16 embeddings, embeds
> query via Voyage, cosine top-k with 600-char snippets. `/api/chat`
> with rate limit (5/IP/24h), semantic cache (24h), daily $100 budget
> cap, off-corpus abstention shortcut (skips Anthropic call). All
> /api/* routes cookie-gated.
>
> **Browser:** ChatIsland + ChatSettingsPanel (Preact). Provider
> abstraction (`AnthropicServerProvider`, `AnthropicBYOKProvider`).
> BYOK via raw fetch + `anthropic-dangerous-direct-browser-access`
> header — no SDK dep, smaller bundle. Citation chips render unknown
> card_ids as literal text (anti-hallucination guard).
>
> **System prompt:** verbatim quoting; abstention is first-class;
> mandatory `[card_id:page]` citations; treat retrieved content as
> untrusted (prompt-injection resistance). Lives in two places now
> (worker side + browser side); test invariants pin the load-bearing
> rules. Tune them together.
>
> **Tests:** worker 15 → 65 (50 new node:test cases). Pytest 63/63.
> 158 pages built.
>
> **Deploy gate:** before chat goes live in production, the operator
> must:
>
>   1. `wrangler kv namespace create CHAT_KV` and put the id in
>      `wrangler.jsonc`.
>   2. `wrangler secret put VOYAGE_API_KEY`.
>   3. `wrangler secret put ANTHROPIC_API_KEY` (paying tier — Claude
>      Code OAuth tokens hit Sonnet 429s).
>
> Without those, the chat surface still ships in the static deploy
> but rate limit / cache / budget degrade off (the handler null-checks
> env.CHAT_KV) and the LLM call returns 502.

# Chat interface — semantic search + RAG over the corpus

## Why

This is the headline feature. Anyone can query the corpus via the
existing keyword search; the chat surface lets them *ask questions* and
get synthesized answers grounded in citations.

Quality bar: every claim cites at least one page. Off-corpus questions
return "no documents discuss this" instead of guessing. The interface
makes the retrieval transparent — you see what was retrieved alongside
the synthesized answer.

## Architecture

Two execution paths behind the same provider interface:

```
                 ┌─ ANONYMOUS / DEFAULT ───────────────────────────────┐
Browser ────────►│ Cloudflare Worker (same as static)                   │
                 │   ├─ Rate limit (5/IP/day)                           │
                 │   ├─ Semantic cache (Workers KV)                     │
                 │   ├─ Retrieval (in-memory cosine over embeddings.bin) │
                 │   └─ Anthropic API (server-funded, sonnet)           │
                 └──────────────────────────────────────────────────────┘
                 ┌─ BYOK / POWER USER ──────────────────────────────────┐
Browser ────────►│ Anthropic API (direct, user's key, opus or sonnet)   │
        │        └──────────────────────────────────────────────────────┘
        └────────► Worker (retrieval only)  ───────────────────────────┐
                   Returns retrieved snippets; browser does the LLM call
                   keeps key out of our infra entirely
```

Static frontend stays on the same Worker. Two modes share the same UI
and the same retrieval path; only the LLM call differs.

### Anonymous (default)

Worker handles:

1. Per-IP rate limit (Workers KV counter, 5/day).
2. Semantic cache lookup (hash of query + top-k retrieved card_ids → cached answer).
3. Query embedding (Voyage / OpenAI; same model as the corpus).
4. Top-k retrieval (cosine, k=8, threshold 0.5).
5. Prompt assembly: system prompt + retrieved page snippets + user query.
6. Anthropic streaming response (server-funded, default model: claude-sonnet-4-6).
7. Citation extraction → /card/[id]#page-N links.
8. Daily global spend cap → graceful degrade to keyword-only search.

### BYOK (power user)

User opens **Settings** in the chat surface, pastes an Anthropic API key.
Stored in `localStorage` only — never sent to our origin. Anthropic key
permissions are respected entirely by the user; we never see, log, or
proxy the key.

Worker still handles retrieval (we'd rather not embed the entire 8.5 MB
vectors.bin in the browser; retrieval needs the whole index). Browser
handles the LLM call directly via `@anthropic-ai/sdk` with
`dangerouslyAllowBrowser: true`.

Flow:

1. Browser → Worker `/api/retrieve` with query → Worker returns top-k
   passages + citation metadata.
2. Browser → Anthropic API directly with retrieved snippets + user
   key → streams response.
3. Browser renders streaming + citations identically to anonymous mode.

Tradeoff: in BYOK mode the user's IP hits Anthropic directly so they
get whatever rate limit Anthropic gives them. They also unlock model
choice (Opus 4.7 instead of Sonnet 4.6) via a settings toggle.

### Provider abstraction

The browser-side LLM call lives behind a provider interface from day
one so adding OpenAI, Mistral, or local Ollama later is a one-file change:

```typescript
interface LLMProvider {
  name: string;
  stream(messages: Message[], opts: StreamOpts): AsyncIterable<Chunk>;
}
```

Implementations:
- `AnthropicServerProvider` — calls our Worker `/api/chat` (anonymous mode)
- `AnthropicBYOKProvider` — calls Anthropic directly with user key
- `OpenAIBYOKProvider` — calls OpenAI directly with user key (post-launch)
- `OllamaProvider` — calls user's local Ollama server (privacy-niche, post-launch)

Settings panel chooses provider; UI is identical regardless.

## Prompt scaffolding

System prompt enforces:

- "Answer only from the provided documents. If the documents don't
  contain the answer, say so explicitly."
- "Every factual claim cites a page in the form `[card_id:page]`."
- "Do not speculate about what the documents *might* mean. Quote
  conservatively."
- "If the user asks about a UAP claim, distinguish between what the
  document reports vs. what the document concludes."

Few-shot examples in the prompt show the citation format and the
"no documents discuss this" abstention pattern.

## UI

- Single chat thread per session (no history persistence in v1).
- User input at bottom; messages scroll up.
- Each assistant message has:
  - Streaming text with inline `[citation]` chips.
  - Citations sidebar: each cited page renders as a card with the
    relevant snippet highlighted, click → opens /card/[id] in a side
    panel.
- "Suggested questions" shown on empty state to demonstrate scope:
  - "What does the FBI's 62-HQ-83894 file say about Roswell?"
  - "Did Apollo 17 astronauts report any anomalies?"
  - "What incidents involved redacted location data?"

## Rate limits + abuse (anonymous mode)

- Per-IP: 5 chats / 24h via Workers KV counter. (Generous enough that a
  curious skeptic can poke; tight enough to bound spend at HN scale.)
- Global: $100/day cap; over → graceful "high traffic, try again or
  bring your own Anthropic key" message that links to BYOK setup.
  Alert via Pushover/Slack hook.
- Semantic cache: hash query + top-k page IDs; identical retrieved set
  + similar query → cached answer for 24h. Catches HN-spike duplication
  (most queries on launch day will be ten variants of "Roswell").
- Abuse signals: prompt-injection patterns (`ignore previous`,
  `<system>`), automated-script UA fingerprints, bulk identical queries
  from same IP. Quietly degrade those to keyword-search-only.

BYOK mode bypasses all of this — user owns their cost and their rate
limit relationship with Anthropic.

## Cost model

Per anonymous chat, rough:

- Embed query (Voyage on Worker side): ~$0.0001
- Anthropic Sonnet 4.6 with ~3k retrieved + 500 query tokens + 800
  response: ~$0.015
- Cache hit: $0

Worst-case launch math:

| Scenario | Anonymous chats | Cache hit rate | Daily spend |
|---|---|---|---|
| HN front page, day 1 | 25,000 | 60% | ~$150 |
| HN front page, day 2 | 8,000 | 80% | ~$24 |
| Settled state | 500 | 50% | ~$4 |
| BYOK power users | unlimited | n/a | $0 (user pays) |

Spend ceiling is the daily cap, not the observed traffic. BYOK
adoption (we'd expect 5–15% of power users) reduces marginal load on
the anonymous tier even further.

### Optional: patron tier (post-launch)

Stripe subscription, $5–10/month, bumps your anonymous quota to
100/day instead of 5. Proceeds fund the anonymous tier. Canonical
"open-source funded by supporters" pattern. Defer until we see real
traffic; ship without if the cost math holds.

## Acceptance

- **Anonymous mode (default):**
  - Sample query "Show me FBI docs on Roswell" returns a synthesized
    answer with at least 3 distinct citations, each linking to a real
    card page.
  - Off-corpus query "Did aliens build Stonehenge?" returns explicit
    abstention, not a guess.
  - Streaming response renders character-by-character; citations
    appear as references are emitted, not after-the-fact.
  - Rate limit kicks in at the 6th request from a single IP within 24h
    with a clear message offering BYOK mode.
  - Per-chat latency < 3s to first token (p50).
- **BYOK mode:**
  - Settings panel accepts an Anthropic API key, stores in
    localStorage, never POSTs the key to our origin (verifiable in
    devtools network tab).
  - With a key configured, chat works regardless of anonymous-tier
    rate limit.
  - Model picker exposes Sonnet 4.6 + Opus 4.7 (BYOK only).
  - Removing the key from settings reverts to anonymous mode.
  - Provider abstraction (`AnthropicServerProvider` /
    `AnthropicBYOKProvider`) is in place; adding a new provider is
    a single new file.

## Open questions

- Which model. Sonnet 4.6 is the default; Opus 4.7 for better reasoning
  costs ~5x and may not move the needle on a corpus this size.
- Conversation history. v1 ships single-turn only; multi-turn requires
  managing context window + relevance decay over turns.
- Streaming citations vs end-of-message. Streaming is harder but the UX
  win is large; ship streaming.
