---
id: curated-finds
type: feature
status: backlog
created: 2026-05-08
priority: high
depends_on: []
---

# Curated finds — "Notable Cases" page

## Why

The chat is the headline feature, but a **hand-curated reading guide**
written from the source documents is what wins journalist trust *and*
demonstrates what the chat can do, before the chat ships.

This is the page that gets bookmarked. Three to five well-written
entries — each with a thesis, cards/pages it draws from, verbatim
excerpts, and explicit "here's what we're not claiming" — does more
for credibility than any chat answer.

It's also the lowest-risk public artifact we can ship: every claim is
backed by a specific page link, written by a human (or a reasoning
agent under human review), no hallucination surface.

## Scope

1. **Astro Content Collection** at `web/src/content/finds/` for
   type-safe Markdown entries. Frontmatter: `slug`, `title`,
   `subtitle`, `tags`, `cards: [card_id]`, `published`, `summary`.
2. **Route** at `/finds` (index) and `/finds/[slug]` (detail).
   - Index: chronological list with title, summary, tag chips.
   - Detail: rendered Markdown with custom components for citations
     (`<Cite card="..." page={n}>...quote...</Cite>`) that auto-link
     to `/card/[id]#page-N`.
3. **Cite component** that fetches the snippet from `/data/pages.json`
   at build time, renders the verbatim quote in a styled blockquote
   with a "→ source" link to the card page.
4. **Header nav addition**: `FINDS` link between SEARCH and DIFF.
5. **Empty state** for the index when no finds are written yet:
   "Curated cases coming soon. In the meantime, browse the full index
   or jump to search."

## Initial entries to seed

Pick 3–5 from the first agent reading pass, with a bias toward
cross-referenced cases (multiple cards / multiple agencies):

- **Apollo 17 Crew Debriefing** (NASA, card `0b298cfc9c65a4d6`) —
  what the mission report actually says about anomalous observations
  vs. what's been claimed about it online for years. The classic
  "the document is more interesting than the rumor" treatment.
- **FBI 62-HQ-83894** — the omnibus 1947–1968 file that's the largest
  single archive in PURSUE. Walk the reader through structure: what
  cases it contains, what's redacted, what the cross-references reveal.
- **Roswell-adjacent material** — every card with "roswell" or
  recognizable Roswell-era dates, with a note on what's new vs. what's
  been in the Black Vault for decades (depends on novelty-detection
  plan landing for the prior-disclosure tagging).
- **DOW Mission Reports / Unresolved UAP Reports pairings** — the
  cards that come in matched pairs (D## paired with PR##) tell a
  story about how the agency catalogs incidents. Worth its own essay.
- **Multi-agency cross-references** — incidents that appear in DOW,
  FBI, and NASA files at the same time. Strong cross-reference signal.

These can be drafted by a reasoning agent (Opus 4.7) reading the OCR
output, with explicit instructions to cite verbatim and abstain when
the documents don't support a claim. Human review before publish.

## Acceptance

- `/finds` lists at least 3 entries with summary text and tag chips.
- `/finds/[slug]` renders Markdown with the `<Cite>` component
  resolving to working `/card/[id]#page-N` links.
- Each entry passes the editorial standard: every factual claim has
  a citation; ambiguity is flagged; the entry says what we *can't*
  determine from the source.
- The page reads like editorial work, not auto-generated text.

## Editorial standards (load-bearing)

- **Verbatim quoting** — quote the document, do not paraphrase, when
  the exact language matters.
- **Abstention is fine** — "the document does not say what observers
  reported" is a legitimate finding.
- **No speculation chains** — don't extrapolate beyond the source.
  If three readers would disagree about what a redacted passage
  implies, write what the document literally shows and stop.
- **Cite the page, not the document** — `card_id#page-3` not
  `card_id`. Specificity matters for journalists who are going to
  follow the link.

## Out of scope

- AI-generated entries with no human review.
- Speculative essays not grounded in the corpus.
- "Top 10" listicle treatment.
- Comments / community contributions.

## Open questions

- Frequency: ad-hoc as the agent surfaces interesting things vs. a
  weekly cadence post-launch. Probably ad-hoc to start.
- Authorship attribution: byline as "BPS AI Software" or a real name?
  (Real name is more accountable, harder to dismiss as bot output.)
- Where curated-finds entries cite the chat itself once chat ships:
  hyperlink with prefilled query? Avoid recursion.
