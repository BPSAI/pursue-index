---
id: documentation-staleness-audit
status: backlog
created: 2026-05-12
priority: medium
depends_on: []
---

# Full-repo documentation staleness audit

## Background

Operator reported 2026-05-12: reading `/methodology` overnight surfaced
references to **Tesseract** in places that should be **Surya** — the
project's OCR engine changed during the pre-v1.0 build-out but the
docs weren't fully re-swept. That single example is almost certainly
not isolated: the repo has accumulated ~50 commits and several major
architectural shifts since the docs were last comprehensively read.

Documentation drift on a public-archive project is a credibility
cost. If a researcher reads the methodology page and the prose
describes one OCR engine but the actual outputs cite a different
one, the burden falls on them to figure out which is real — which
they will reasonably interpret as a sign the rest of the docs are
similarly out of date.

## What "stale" means in this codebase

Three drift classes worth checking:

1. **Tool / engine names that have moved** — Tesseract → Surya
   (OCR engine), pip-install patterns that should be hash-pinned,
   secret names that have rotated since first-mention.
2. **Numeric facts that have shifted** — corpus card counts (was 161
   at v1.0.0, now 158), page counts (was 4,153, now 4,161 after the
   replacement-card pipeline), embedding row count (was 4,119, now
   4,127 deployed), pricing numbers (Haiku rates, Voyage rates), cron
   cadence (was 6h, now 30 min).
3. **Architectural claims that have nuanced** — "PDFs self-hosted
   from R2" is true but the byte-history layer wasn't there at first;
   "OCR pipeline" descriptions predate the LLM-cleaned overlay; "the
   manifest" descriptions predate the snapshot rotation; etc.

## Where to look

| File / surface | Drift risk |
|---|---|
| `web/src/pages/methodology.astro` | High — operator-flagged Tesseract; also pre-dates LLM-cleaned overlay's full-corpus run |
| `web/src/pages/about.astro` | Medium — corpus stats, pipeline description |
| `web/src/pages/cite.astro` | Medium — citation form references |
| `web/src/pages/api.astro` | Medium — Worker constants, surface descriptions |
| `web/src/pages/index.astro` | Low — operator-curated, less drift |
| `README.md` (repo root) | High — first-impression doc for any visitor |
| `docs/architecture.md` | High — likely never updated post-v1.0 |
| `docs/ocr-benchmark.md` | High — directly OCR-engine related |
| `SECURITY.md` | Medium — refreshed 2026-05-12, but inside-section content may have moved |
| `web/src/content/finds/*.mdx` | Low-medium — most are self-dated, but cross-link claims may have drifted |
| `.paircoder/plans/*.md` | Status field accuracy + corpus-numeric statements |
| `pyproject.toml` description / comments | Low |
| `worker/index.js` inline docs | Low (already touched recently) |

## Approach

The audit is editorial work — fast to dispatch as a sub-agent pass,
slow to do well by hand. Recommended:

1. **Dispatch an agent** (general-purpose or a fresh nayru read of
   docs-only) with: "Walk every file in this list. For each prose
   claim that could be checked against current state of the
   repository, verify or flag it. Report a structured punch-list."
2. **Operator review** of the punch-list — some claims are
   self-correcting (numeric updates), some need editorial judgment
   (does the architectural description need to be rewritten or
   just patched?).
3. **Single rolled-up PR** with all the doc updates rather than
   one per drift item (per the operator's bundled-commits memory).

## Open questions

1. Do we want to add a "last reviewed" footer to each docs page,
   with a commit date? Catches drift early but adds maintenance
   surface.
2. Is there value in CI-asserting some claims (e.g., a test that
   reads `pages.json`'s row count and asserts the methodology page's
   stated number matches)? Probably yes for the highest-traffic
   numerics; not worth the lift for editorial prose.
3. Should the `/finds` entries be in scope? They're more
   self-contained editorial pieces; their drift surface is
   smaller. Probably skip for the first pass; revisit if /finds
   adds new entries that reference shifting infrastructure.

## Estimated effort

~2 hours operator-attended (or ~4 hours agent-dispatched with
operator review of the punch-list). Lower priority than active
feature work but high impact on "first-time researcher reads our
docs" experience.
