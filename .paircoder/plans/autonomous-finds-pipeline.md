---
id: autonomous-finds-pipeline
type: feature
status: backlog
created: 2026-05-10
priority: medium
depends_on: [black-vault-reference]
---

# Autonomous Finds Pipeline

## Summary

A continuously-running pipeline that surveys the PURSUE corpus on every
new tranche, scores each card for novelty against existing finds entries
and an external reference corpus, drafts publish-ready entries for the
strongest candidates, and submits them as pull requests against
pursueindex.com for editorial review.

The pipeline itself is **not** part of the public pursue-index repo. It
lives as a private internal artifact because it relies on internal IP
(voice profile, agent infrastructure) that is not appropriate for public
distribution. The public repo only sees the output: a pull request
opened by a bot account containing a single `.mdx` file ready for
editorial review.

## Why

The first phase of `/finds` was hand-crafted: 12 entries written by a
human editor (and once, in PR #32, by a reasoning agent under a strict
editorial brief). The editorial bar is established and the page works.

The next phase is **coverage**. The corpus has 116 PDF cards on Release
01, with more tranches coming. Every card deserves a reading pass; not
every card deserves an entry. A pipeline that does the reading pass
autonomously, surfaces the candidates worth publishing, and writes them
in the operator's narrative voice — under editorial review — converts
"this page is great when David writes one" into "this page grows
continuously without operator-burning."

## Architecture: Public / Private Split

The pipeline crosses a trust boundary. The public pursue-index repo
contains the corpus, the site, and the rendered finds entries. The
private infrastructure contains the agent fleet, voice profiles, and
orchestration. The pipeline lives entirely on the private side and
reaches into the public repo only through the same surface a human
contributor would use: pull requests.

```
┌────────────────────────────────────────────────────────────────┐
│  PRIVATE INFRASTRUCTURE                                          │
│                                                                  │
│   pursue-finds-pipeline  (private repo or sibling-project       │
│      within private orchestration / dispatch infrastructure)    │
│      ├─ pulls pursue-index manifest (HTTPS, public)             │
│      ├─ pulls pursue-index existing /finds entries (Git, public)│
│      ├─ runs novelty detection                                  │
│      │    └─ against existing finds + Black Vault reference     │
│      ├─ ranks candidates                                        │
│      ├─ dispatches voice-disciplined writer (private agent      │
│      │    fleet with private voice profile)                     │
│      └─ opens PR against public pursue-index via bot account    │
│                                                                  │
└────────────────────────────────────────────────────────────────┘
                                │
                                │  PR creation (bot account)
                                ▼
┌────────────────────────────────────────────────────────────────┐
│  PUBLIC pursue-index REPO                                        │
│                                                                  │
│      ├─ existing 6h cron (poll-pursue.yml) — unchanged          │
│      ├─ existing manifest, OCR, embeddings (public)             │
│      ├─ existing /finds/*.mdx (public content)                  │
│      └─ receives PR from the private pipeline                   │
│            └─ human editorial review (operator)                 │
│            └─ merge or close per editorial judgment             │
│                                                                  │
└────────────────────────────────────────────────────────────────┘
```

Boundaries:

| Concern | Lives in | Why |
|---|---|---|
| Voice profile (operator voice profile) | Private fleet repo | Closely-guarded craft tool; not for public distribution |
| Writer agent + enforcement rules | Private voice-disciplined writer agent | Internal IP; voice fidelity is the product |
| Pipeline orchestration | Private fleet (sibling or inside private orchestration / dispatch infrastructure) | Couples private agents; couples to private inter-agent transport |
| Pursue-index novelty pipeline | Public pursue-index | Already exists; library-callable from private side |
| Manifest, OCR, embeddings | Public pursue-index | Already public artifacts |
| Generated `.mdx` finds entry | Public pursue-index (after PR merge) | Public content; the editorial artifact |

## Gate: PR + Human Review (v1)

Same flow that worked for PR #32 (D32 Syria entry):

1. Pipeline drafts entry, validates against voice enforcement rules and
   structural checks (length, citation density, abstention block
   present).
2. Pipeline opens PR against pursueindex.com via bot account, labeled
   `editorial-review-required`. PR body includes the candidate's
   novelty score, the cards it cites, and a "do not merge without
   editorial review" notice.
3. Operator reviews the prose itself (the load-bearing artifact).
4. Operator merges or closes; if closing, optionally adds a comment
   explaining the editorial reason so the pipeline can record it.

Future modes (deferred to v2):
- Threshold-autonomous: if voice enforcement passes AND novelty score
  exceeds a calibrated threshold AND length is in range AND the PR sits
  untouched for 48h, auto-merge. Requires confidence built from a
  multi-week period of operator-approved PRs.
- Hybrid: PR opens automatically; auto-merges if no editorial
  intervention. Provides a release-valve without losing oversight.

## Budget Discipline

The pipeline must not burn API budget on:

1. Cards already covered by existing finds entries (cross-reference
   check before any drafting).
2. Cards with low novelty against the reference corpus (skip-or-stage
   threshold tuned against Black Vault calibration).
3. Cards that fail a cheap-model pre-read ("is there even a story
   here?"). A small local model passes first; only candidates that clear
   that bar consume frontier-model writer tokens.
4. Cards that have failed editorial review in the past (if operator
   closed a PR with an editorial-decline reason, the pipeline records
   it and does not redraft the same card).

Hard caps per tick:
- Max 1 frontier-model draft per pipeline tick (one entry per 6h cron
  cycle is plenty; corpus grows slowly).
- Max 4 frontier-model drafts per day (covers manual re-runs).
- Per-card cap: at most 2 drafts before the card is marked as "passed
  on" and excluded from future ticks unless operator unblocks.

## Pipeline Stages (Sense / Plan / Execute / Learn)

The pipeline is a `BaseAgent` subclass following the lifecycle pattern
the private agent fleet uses.

**Sense**:
- Fetch the pursue-index manifest (HTTPS).
- Pull the latest commit of the public repo, read `web/src/content/finds/`
  to know what's already covered.
- Load the cached pipeline state (which cards have been seen, which
  have been declined, which are in-flight as open PRs).
- Identify the delta: cards in the manifest that the pipeline hasn't
  yet evaluated.

**Plan**:
- For each delta card, compute novelty score: cosine similarity against
  existing finds entries (embedded) + against the reference corpus
  (Black Vault when available).
- Apply the budget filter: skip already-covered, low-novelty, and
  previously-declined cards.
- Rank remaining candidates by a composite score (novelty + corpus
  representativeness + completeness of OCR).
- Pick the top candidate (one per tick).

**Execute**:
- Dispatch the voice-disciplined writer agent (the writer agent or
  successor) with: card metadata, full OCR text, paired video
  descriptions (if
  any), existing finds entries as style/voice anchors, editorial bar
  prompt block.
- Receive draft .mdx output.
- Run structural validation: word count in range, ≥3 verbatim citations,
  abstention block present, frontmatter complete.
- If validation fails: discard, mark card for retry-once, log the
  failure mode.
- If validation passes: prepare PR — branch name, commit message, PR
  body with novelty score and cited cards.
- Open PR via bot account.

**Learn**:
- Record the PR URL alongside the card_id in the pipeline's state.
- Watch for PR resolution (merge / close).
- On merge: card is "covered"; never re-evaluated.
- On close with editorial-decline reason: record the reason; the card
  is "passed on" for v1 (operator unblock required to retry).
- On close without comment: treat as soft-decline; retry once after 7
  days with adjusted prompt (if structural-only issue).

## Newsletter Layer (Optional, Deferred)

Once the pipeline is producing entries on a regular cadence, a weekly
digest is a natural follow-on:

- Subscribe-only mailing list (Buttondown, ConvertKit, or self-hosted)
- Weekly: aggregate finds entries published in the prior week, render
  a digest in the same voice via the writer agent, send.
- Each entry in the digest links to the full /finds page on
  pursueindex.com.

Cost: low. Implementation: a separate weekly cron in the pipeline +
mailing list integration. Deferred until the core pipeline is operating
at steady-state.

## Dependencies

- **Black Vault reference corpus** (`black-vault-reference.md`) —
  novelty cross-reference is meaningfully different from "matches an
  existing entry" only when there is an external reference corpus to
  measure against. Without Black Vault, the pipeline can still avoid
  duplicates against existing finds entries, but the novelty signal is
  weak.
- **Voice profile maturity** — the operator voice profile in the
  private fleet needs to be trained against the 12 existing finds
  entries as voice anchors. Confirmation required that the profile
  consumes those entries during enforcement.
- **Bot account setup** — a GitHub bot account with PR-creation rights
  on pursueindex.com (and only that; no merge rights, no settings
  changes). Operator-owned, clearly labeled.
- **Writer agent maturity** — the writer agent must reliably produce
  output that passes the structural validation block. The PR #32
  demonstration was a single supervised draft under operator-supplied
  brief; the pipeline drafts unsupervised against an editorial bar
  prompt block. The gap is non-trivial.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Pipeline generates an entry the operator wouldn't approve, but the PR sits in their queue and creates noise | Medium | Strong structural validation before PR open; per-card cap; clear editorial-decline reason recording |
| Voice profile drift produces entries that read off-voice | Medium | Operator reviews each PR; failed entries close with editorial-decline reasons; profile refined against the feedback |
| Bot account credentials compromised | Medium | Operator-owned bot account; rotation policy; PR creation only (no merge / no settings) |
| Pipeline writes about content the operator didn't intend to cover for editorial reasons | Low | Operator can pre-blocklist specific card_ids in pipeline state |
| Budget caps fail; pipeline burns more tokens than expected | Low | Hard per-tick / per-day caps; pipeline exits if cap reached |
| Black Vault never materializes; novelty signal stays weak | Low | Pipeline runs against existing-finds-only cross-reference as a fallback; degraded but functional |

## Out of Scope

- Building the agent fleet (assumed to exist within the private infrastructure).
- Publishing the voice profile or any private agent code.
- Auto-merge of PRs without operator review (v1 is PR + human review only).
- A community-contribution layer where external readers can suggest entries.
- A real-time generation surface ("write me a finds entry on demand").

## Open Questions for Operator

1. Where exactly does the pipeline live within the private fleet — new
   sibling repo, or inside the private orchestration / dispatch
   infrastructure as a workspace it dispatches, or inside a planned
   watcher agent as a specialized watcher?
2. Bot account: existing private fleet bot, or new one specifically for
   pursue-index editorial PRs?
3. Cadence: pipeline ticks on every 6h cron (passive), or only when
   the manifest changes (event-driven)?
4. Ordering: do we want this pipeline before, after, or in parallel
   with the Black Vault reference corpus work?
5. Are we prepared to refine the voice profile over time based on
   editorial-decline reasons, or does v1 freeze the profile and only
   ship entries the current profile produces cleanly?
