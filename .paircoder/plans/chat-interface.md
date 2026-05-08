---
id: chat-interface
type: feature
status: backlog
created: 2026-05-08
depends_on: [embed-stage, ui-redesign-alien]
priority: high
---

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

```
Browser ──► Cloudflare Worker / Vercel Edge ──► Anthropic API
   │              │
   │              ├─ Retrieval (in-memory cosine over embeddings.bin
   │              │           shipped at deploy time, ~50 MB)
   │              └─ Optional semantic-similarity cache (KV/Redis)
   │
   └─ Streams Claude response via SSE; renders citations live
```

Static frontend stays on Pages. The Worker handles:

1. Query embedding (Voyage / OpenAI; same model as the corpus).
2. Top-k retrieval (cosine, k=8, threshold 0.5).
3. Prompt assembly: system prompt + retrieved page snippets + user query.
4. Anthropic streaming response.
5. Citation extraction from response → linked back to /card/[id]#page-N.

The frontend's `/chat` surface streams the answer + a citations sidebar
that updates as references arrive.

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

## Rate limits + abuse

- Per-IP: 30 chats / hour at the edge (Workers KV counter).
- Global: $50/day cap; over → graceful "high traffic, try again"
  message. Alert via Pushover/Slack hook.
- Semantic cache: hash query + top-k page IDs; identical retrieved set
  + similar query → cached answer for 24h. Catches HN-spike duplication.
- Abuse signals: prompt-injection patterns (`ignore previous`,
  `<system>`), automated-script UA fingerprints, bulk identical queries
  from same IP. Quietly degrade those to keyword-search-only.

## Cost model

Per chat, rough:

- Embed query: ~$0.0001
- Anthropic Sonnet 4.6 with ~3k retrieved + 500 query tokens + 800
  response: ~$0.015
- Cache hit: $0

At 10k chats/day during a launch spike: ~$150/day worst-case, much less
with cache. Below the alert threshold, but visible.

## Acceptance

- Sample query "Show me FBI docs on Roswell" returns a synthesized
  answer with at least 3 distinct citations, each linking to a real
  card page.
- Off-corpus query "Did aliens build Stonehenge?" returns explicit
  abstention, not a guess.
- Streaming response renders character-by-character; citations appear
  as references are emitted, not after-the-fact.
- Rate limit kicks in at 31st request from a single IP within an hour.
- Per-chat latency < 3s to first token (p50).

## Open questions

- Which model. Sonnet 4.6 is the default; Opus 4.7 for better reasoning
  costs ~5x and may not move the needle on a corpus this size.
- Conversation history. v1 ships single-turn only; multi-turn requires
  managing context window + relevance decay over turns.
- Streaming citations vs end-of-message. Streaming is harder but the UX
  win is large; ship streaming.
