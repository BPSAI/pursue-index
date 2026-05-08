---
id: phase-2-roadmap
type: feature
status: backlog
created: 2026-05-08
priority: high
---

# Phase 2 — pursueindex.{com,ai} public launch

## North star

Be the canonical, citable, transparent public interface to the DOW PURSUE
corpus. First mover wins the credibility prize: HN front page, journalist
references, BPS reputation lift. Lose it by shipping a hallucinating chat
over OCR garbage.

The moat is **quality + verifiability**, not "we built a chat first."
Anyone with an OpenAI key can build a chat. We win by being the version
that doesn't lie about UFO documents.

## Sequence

Plans below are dependency-ordered. Items in **bold** are critical-path.

| # | Plan                                                       | Depends on | Why first  |
|---|------------------------------------------------------------|------------|------------|
| 1 | ~~[ocr-gpu-surya](./ocr-gpu-surya.md)~~ ✅ shipped          | —          | Surya engine landed; ~1.87× faster than Tesseract on the FBI scans. |
| 2 | ~~[ocr-llm-fallback](./ocr-llm-fallback.md)~~ ✅ shipped    | (1)        | Anthropic vision behind `engine="auto"`; FBI cover page went from gibberish to full transcription, ~$0.10/15pp at Sonnet rates. |
| 3 | **[ocr-benchmark](./ocr-benchmark.md)**                    | (1)(2)     | Now unblocked (`--force` flag landed with LLM fallback). A/B harness on a golden set, methodology numbers for the launch. |
| 4 | **[review-correct](./review-correct.md)**                  | (3)        | Human-in-the-loop (or agent-in-the-loop) corrections for the long tail. |
| 5 | ~~[embed-stage](./embed-stage.md)~~ ✅ shipped              | (3)        | `pursue embed run` Voyage-3 pipeline; in-browser float16 payload ~8.5MB. Awaiting VOYAGE_API_KEY for the live pass. |
| 6 | ~~[ui-redesign-alien](./ui-redesign-alien.md)~~ ✅ shipped  | —          | Declassified-terminal aesthetic landed; 152-page build, 112KB bundle. |
| 7 | **[chat-interface](./chat-interface.md)**                  | (5)(6)     | The headline feature. Streams from a backend, RAG over (5), citations mandatory. UNBLOCKED by embed-stage shipping. |
| 8 | **[production-launch](./production-launch.md)**            | (7)        | Domain DNS, rate-limits, abuse handling, methodology page, HN post. CF Pages migration runbook is at `docs/runbooks/cloudflare-pages-migration.md`. |
| 9 | [curated-finds](./curated-finds.md)                        | —          | "Notable Cases" page — hand-curated reading guide. Authority play, can ship before chat. |
| 10 | [novelty-detection](./novelty-detection.md)               | (5)        | Per-page cosine similarity vs Black Vault reference corpus → "new vs previously disclosed" tags. The citation moat. |

## Non-goals for phase 2

- Postgres / FastAPI ingest/serve stages. The static site + edge function
  for chat is sufficient at this corpus size; revisit if it grows past
  what client-side retrieval handles cleanly.
- DVIDS video ingestion. UAP videos are interesting but they're a separate
  problem (frame extraction, vision models). Phase 3.
- Multi-tranche analytics (trend over time). We only have Release 01;
  the diff page is enough until Release 02 lands.
- User accounts / saved chats. The first version is anonymous, rate-limited,
  cache-forward. Account systems are scope creep.

## Anti-moats and risks

- **OpenAI/Anthropic ship document upload features.** They already have, in
  fairness; what they don't have is the curated, hash-pinned, version-tracked
  corpus with a manifest pipeline. Lean into that.
- **Random rebrand sites scrape and republish.** Public-domain source means
  we can't legally stop it. Defense: be the primary citation, the one with
  methodology disclosed, the one with corrections logged.
- **Hallucination.** A single confident wrong answer from the chat — quoted
  in a journalist's article — is reputational damage. Mitigations: every
  claim cites; "I can't find that" is a first-class answer; abstention is
  trained into the prompt; retrieval surfaces source text alongside the
  generated answer so users see what was retrieved.
- **HN spike.** If we hit the front page, expect 10k+ unique queries in
  a few hours. Edge cache + semantic-similarity LLM cache + per-IP rate
  limit. See production-launch plan.

## Brand & domain

- **pursueindex.com** — canonical user-facing site.
- **pursueindex.ai** — `api.pursueindex.ai` for the chat backend; root
  redirects to `.com`. Keeps the AI angle visible without competing for trust.
- Visual identity: declassified-terminal aesthetic. See ui-redesign-alien.

## Success criteria for launch

- Every chat answer cites at least one source page with a working link to
  the underlying war.gov PDF.
- Sample query "Show me everything FBI on Roswell" returns the right
  documents and a synthesized answer that doesn't add facts.
- Sample query "Did Apollo 17 see anything?" returns the actual debriefing
  with the relevant section quoted, not a generic UFO summary.
- "I don't know" / "no documents discuss this" is returned for off-corpus
  questions ("did aliens build the pyramids", etc.).
- Rate limit holds under 100 req/s synthetic load.
- HN post drafted, methodology page live, FAQ covers "how accurate is the OCR."
