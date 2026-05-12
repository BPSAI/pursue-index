---
id: card-rename-handling
type: feature
status: shipped
created: 2026-05-12
shipped: 2026-05-12
priority: high
depends_on: []
---

> **Shipped 2026-05-12.** Steps 1-7 of this plan landed in tranche
> `65572b38d27c` ingestion (commits `9dd7d9c`, `2aeef64`, `4959ff3`).
> The byte-archive layer, rename-detection policy, replacement-card
> pipeline, and pre-approval TOCTOU re-fetch audit are all live.
> Kept as a historical record of the design.


# Safe ingestion of upstream renames and re-cataloging

## Recommendation

**Build a four-layer safety net around upstream re-cataloging events
before ingesting tranche `65572b38…` (the current 133-rename event).
Treat byte_sha256 as the document's true identity; treat `card_id` as
a citation handle that upstream is allowed to change. Preserve every
prior identity. Quarantine any change that could be tampering disguised
as a rename.**

**Critical: the safety net gates editorial publication, never
archival capture.** The poll workflow continues to run every 30
minutes and the byte-archive layer captures every new byte stream
upstream serves, regardless of operator approval state. Only the
deployed-corpus-state change (manifest promotion + OCR/embed/deploy)
is gated.

The byte-archive layer (shipped 2026-05-11) already discovers renames
cryptographically — the NASC-State `aa3097b4 ↔ 9e2c2621` finding
yesterday proves this works at the document level. The gap is policy
and tooling around that primitive: we don't yet have a way to declare
"upstream renamed X to Y" and have downstream surfaces (citations,
finds entries, worker URLs) follow.

## Continuous protection layer (never gated)

Before discussing the operator-gated parts of the system, the always-on
parts need to be named clearly because the design's integrity depends
on them being unattended-safe:

| Layer | Triggered by | Operator-gated? |
|---|---|---|
| **Poll** (`*/30 * * * *`) | CSV sha change | Never. Runs unattended. |
| **Byte-archive** | Poll's detected change | Never. Append-only, content-addressed (`archive/<sha>.<ext>` is IfNoneMatch-protected). Captures every new byte stream upstream serves under any URL. |
| **Tranche-diff report generation** | After poll detects change | Never. Auto-runs, writes `.paircoder/plans/tranche-diff-<csv_sha>.md`, commits it. |
| **Daily verify cron** | 06:07 UTC cron | Never. Re-hashes every archived asset, opens `silent-overlay-detected` or `preserved-tampered` if anything mutates. |

If upstream drops a tranche at 3 AM operator-local: the poll catches
it within 30 minutes, both primary and backup R2 capture the bytes
content-addressed, the tranche-diff report lands committed to the
repo for operator's morning review. **No bytes can be missed.**

The operator gate (below) only blocks the *deployed-corpus-state
change* — manifest promotion, OCR/embed/deploy rebuilds, card_id
shifts that propagate to atlas/search/gallery indexes. Until that
gate clears, the public site continues to serve the prior approved
manifest. Archival capture is independent of editorial publication.

## Preservation guarantee

Once a card_id enters the registry, it is preserved forever as a
contract, not as a side effect:

- **`archive/<byte_sha>.<ext>` keys** are append-only by R2-level
  `IfNoneMatch: "*"` on every PUT. Bytes that landed on day N are
  reachable byte-identical on day N+1000, regardless of any
  subsequent operator action, key compromise, or buggy script run.
- **`<card_id>.<ext>` current-pointer keys** are never deleted.
  When upstream renames, the old current-pointer key stays
  addressable; the new card writes its own current-pointer at the
  new card_id without disturbing the old one.
- **Registry rows** are append-only JSONL — never edited, never
  deleted, never reordered. A row recording the byte_sha of
  card_id X on date D is a permanent receipt.
- **Aliases** are append-only — never edited, never deleted. If an
  alias must be revoked, a new row with `method: "operator_revoke"`
  is appended; the original alias row remains for audit.
- **`/removed`** entries are preserved indefinitely as the
  editorial-public face of upstream removals; pinned into the
  integrity layer by `r2_pin_removed.py` so they're under the same
  daily byte-verify coverage as manifest cards.

Card_id collisions between old and new identities are
not a concern: `card_id = sha256(asset_url ‖ title)[:16]` provides
64 bits of entropy, against ~158 current cards growing linearly.
Birthday-collision probability for 16-hex-char prefixes at this
scale is ~$10^{-15}$. Different `(url, title)` inputs always
produce different card_ids by construction.

## Problem statement

On 2026-05-12 upstream restructured 133 of 158 manifest cards. The
new naming convention is:

- Zero-padded card numbers (`D3` → `D003`, `D62` → `D062`)
- Some categories renamed (`D33 Mission Report Greece` → `PR033
  Unresolved UAP Report …` — D-codes appear to be promoted/demoted
  between resolved-mission and pending-resolution categories)
- Standardized location-name patterns
- New asset filenames matching the new card numbers

Because `card_id = sha256(asset_url || title)[:16]`, **every renamed
card gets a new card_id**. Naively re-running the scrape pipeline
against the new CSV would:

1. Detect 133 "new" cards (their new (url, title) tuples)
2. Detect 133 "removed" cards (their old (url, title) tuples)
3. Treat the removed cards the way `/removed` treats genuinely-pulled
   ones — a misclassification of what's actually a rename
4. Break every `/finds/*.mdx` entry that cites an old card_id
5. Leave 133 R2 keys at old card_id paths plus 133 new R2 keys for
   the same bytes — duplicating ~5 GB of storage

The damage from naive ingest is reversible (we never delete), but it
would be an editorial mess and would obscure two genuinely-different
threats:

- **Net-new upstream content** (FBI Photo B-series, State Cable 004 —
  things we want)
- **Tampering disguised as a rename** (the threat model the operator
  named 2026-05-12: "they will remove entire sections, silently edit,
  change names or metadata in an attempt to appear compliant while
  erasing or augmenting the tranches")

## Trust hierarchy — three classes of upstream-presented change

Every new `(asset_url, title)` tuple in an incoming tranche falls into
exactly one of these classes:

### Class A: Confirmed rename

- New `(url, title)` tuple
- After fetching the bytes, `byte_sha256` collides with an existing
  registry entry under a different card_id

**Disposition: safe.** Same document, two citation handles. Establish
an append-only alias `old_card_id → new_card_id` in
`data/card-aliases.json`. Both card identities remain in the registry.
The R2 archive layer already deduplicates by byte_sha so no extra
storage is consumed. Worker resolves either citation handle to the
same bytes.

### Class B: Net-new content

- New `(url, title)` tuple
- New `byte_sha256` (no collision)
- No title-continuity heuristic match against any existing card

**Disposition: ingest normally.** This is genuinely-new upstream
content — exactly what the corpus is for. Treat as a first-time card.

### Class C: Suspicious replacement

- New `(url, title)` tuple
- New `byte_sha256` (no collision)
- Title-continuity heuristics match an existing card (same numeric
  identifier in a known format, same date, same location, etc.)

**Disposition: quarantine.** Do NOT establish an alias. Ingest as a
separate card under its new card_id. Surface as a
`tamper-via-rename-suspected` GitHub issue with the full byte-diff
attached: old byte_sha, new byte_sha, old PDF page count, new PDF
page count, OCR-text levenshtein distance on the first N pages,
side-by-side title comparison. **Every Class C goes to manual
operator review.** No automatic-approval rule is exposed — until a
solid trust mechanism for distinguishing legitimate re-redactions
from tampering exists, the human is the trust mechanism. The cost
(operator review time per quarantined item) is bounded by the
heuristic's specificity and is acceptable at the corpus's current
scale.

The class boundary between B and C is the heuristic — a card with
title `DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024`
matches `DOW-UAP-D032, Mission Report, Syria, October 2024` enough
to warrant quarantine (same Syria/2024 incident handle), while
`FBI Photo B021` has no continuity match to anything and goes to B.

## Title-continuity heuristics

Quarantine triggers if ANY of these match a prior card:

1. Same agency + same incident_date (when both non-null and not "N/A")
2. Same incident_location (when non-empty and not "N/A")
3. Numeric identifier overlap: extract the integer from titles
   matching `(DOW|NASA|FBI)-UAP-(D|VM|PR|VID)?\d+` and compare across
   prefix mappings (e.g., D33 → D033 → PR033 all share `33`)
4. asset_filename Levenshtein distance ≤ 8 against any prior filename

Heuristic false-positives (Class B incorrectly flagged as C) cost
operator review time. Heuristic false-negatives (Class C incorrectly
treated as B) cost everything — alias gets established for a
not-actually-rename. **Bias the heuristic to over-flag.** Operator
reviews quarantined items individually; the cost is bounded.

## Data structures

### `data/card-aliases.json`

Append-only JSON list. Each row records an established alias:

```json
[
  {
    "old_card_id": "aa3097b4c549a67a",
    "new_card_id": "9e2c2621d67dde12",
    "byte_sha256": "aba3ec3b8ef0240364308cf046ccbfcd252c5a5d7ef470d696b72c1f41b2502d",
    "established": "2026-05-12T19:30:00Z",
    "method": "byte_collision",
    "tranche_sha256": "65572b38d27c3bc1af2c3206614913d4d491aea2b0d7d883e2334eaff3a44a8d",
    "old_title": "59_64634_711.5612[7-2852",
    "new_title": "59_214434_SP 16 [7.18.1963]",
    "old_asset_filename": "59_214434_sp_16_7.18.1963.pdf",
    "new_asset_filename": "59_214434_sp_16_[7.18.1963].pdf"
  }
]
```

`method` is one of:
- `byte_collision` — established because byte_sha matched (Class A)
- `operator_manual` — operator explicitly aliased two cards via CLI
  (e.g., after concluding that a Class C quarantined card is in fact
  a legitimate re-redaction the upstream owns and we accept)

Aliases are never edited or deleted. If we ever need to revoke one,
we append an inverse row with `method: "operator_revoke"`. The chain
is queryable from history.

### `data/tranche-approval-log.jsonl`

Append-only record of operator approvals of tranche-diff reports.
Each row: `{tranche_sha256, approved_at, classes: {A: N, B: N, C: N},
operator_note}`. Without an entry here, `pursue scrape run` refuses
to proceed against this tranche.

### `scripts/tranche_diff.py` output schema

JSON to stdout, also written to `.paircoder/plans/tranche-diff-<sha>.md`
for committable review. Format:

```
{
  "tranche_sha256": "65572b38...",
  "prior_manifest": "data/manifests/snapshots/0d7e9ba1....json",
  "summary": {
    "renames_confirmed": 132,
    "new_content": 4,
    "quarantined": 1,
    "removed": 3,
    "field_only_changes": 9
  },
  "renames_confirmed": [
    {"old_card_id": "...", "new_card_id": "...", "byte_sha256": "...", "title_change": "...", ...}
  ],
  "new_content": [{"new_card_id": "...", "title": "...", "byte_sha256": "..."}],
  "quarantined": [{"new_card_id": "...", "matched_against": "old_card_id", "reason": "title-numeric overlap + same incident_date", "byte_diff": {...}}],
  "removed": [...],
  "field_only_changes": [{"card_id": "...", "field": "...", "old": "...", "new": "..."}]
}
```

## Worker behavior

### `/card/<id>`

1. Look up `<id>` in current manifest. If found, render normally.
2. If not found, look up in `card-aliases.json`:
   - If `<id>` is an `old_card_id`, HTTP 301 to `/card/<new_card_id>`
     with header `X-Pursue-Aliased-From: <id>`
   - If `<id>` is a `new_card_id` somehow not in the manifest, log
     and 404 (shouldn't happen — would indicate registry drift)
3. If not in manifest and not in aliases, look up in
   `removed-cards.json`. If preserved-as-removed, render the
   `/removed/<id>` view.
4. Else 404.

### `/pdf/<id>.pdf`

Continues to serve from R2 at `<id>.pdf` key. Append header
`X-Pursue-Aliased-To: <new_card_id>` if `<id>` has an alias. Bytes
served unchanged — the preservation copy stays addressable at its
original card_id forever.

### `/api/retrieve` and other JSON surfaces

Returned card objects include `aliased_from: [...]` listing every
old card_id that resolves to this new one. Lets external consumers
follow the rename chain.

## Pipeline integration

### Pipeline split: detection vs ingestion

To keep the always-on capture layer un-gated while the editorial
publication layer is gated, the existing `pursue scrape run` command
is split into two:

- **`pursue scrape run`** — fetches the upstream CSV, writes raw
  bytes to `data/raw/csv/<csv_sha>.csv`, refreshes
  `data/manifests/snapshots/<csv_sha>.json` (the historical record),
  invokes the byte-archive layer (`r2_archive_assets.py`), and runs
  `tranche_diff.py` to emit `.paircoder/plans/tranche-diff-<sha>.md`.
  **Never gated.** Safe to run from the poll workflow on every
  detected CSV change.
- **`pursue ingest run`** — promotes the new snapshot to
  `data/manifests/latest.json`, kicks the OCR/embed/clean stages
  for any new cards or new byte_shas, rebuilds the deployed
  artifacts (pages.json, embeddings.bin, atlas-layout.json, etc.),
  and commits everything. **Gated on tranche-approval** per the
  next subsection.

The poll workflow runs `pursue scrape run` exclusively. Operator
runs `pursue ingest run` after reviewing the tranche-diff report.

### `pursue ingest run` gate

Before promoting a new tranche into the deployed manifest:

1. Compute incoming CSV sha256 from `data/last-known-csv-sha.txt`
   (already updated by the poll workflow on detection).
2. Read `data/tranche-approval-log.jsonl`. If this sha is approved,
   proceed.
3. If not approved, refuse to proceed. Operator-facing error:

   ```
   refusing to ingest unapproved tranche 65572b38...
   tranche-diff report: .paircoder/plans/tranche-diff-65572b38.md
   review, then approve with:
     pursue ingest approve --tranche 65572b38 --note "..."
   or override (NOT RECOMMENDED) with:
     pursue ingest run --skip-tranche-gate
   ```

4. After ingest completes, run a post-ingest audit (next section).

The override flag exists for emergency response (e.g., operator
confirms a tranche manually and needs to ship without going through
the approval CLI). Override use is logged to
`data/tranche-approval-log.jsonl` with `method: "operator_override"`.

### Post-ingest tampering audit

For every alias established in this run:

1. Re-fetch the upstream bytes at the new asset_url.
2. Re-fetch the archived bytes from R2 at the new card_id's
   `archive/<sha>.<ext>` key.
3. Assert sha-identity between (a) the upstream bytes now, (b) the
   archived bytes, (c) the original old-card_id archive entry.

Any failure means: between when `tranche_diff` ran and when scrape
finished, upstream served different bytes — the rename was being
used as cover for content substitution. Auto-rollback the alias
(append a revoke row to `card-aliases.json`), quarantine the new
card_id, file a P0 `tamper-via-rename-confirmed` issue.

## Editorial / finds-entry resilience

Finds entries continue to cite the **card_id they were written
against**. The worker alias resolver makes their citations continue
to resolve. No prose changes are required when a rename happens —
the `<Cite card="aa3097b4c549a67a" page={N} ... />` component still
works because `/card/aa3097b4c549a67a` 301s to the new card.

Optionally, after an operator-approved rename, the editorial pass
can choose to update the finds entry to cite the new card_id. The
NASC-State entry already includes both card_ids in its cards array
and preservation table — that's the explicit pattern when both
identities are editorially meaningful.

For the docs-staleness audit's purpose, finds entries should add a
new check: every cited card_id should resolve to *some* current card
(via direct manifest match or via alias chain). A test in
`tests/unit/test_finds_citations.py` could enforce this on CI.

## Implementation order

1. **This plan + operator review** — confirm trust hierarchy, the
   B/C heuristic, the data structures. Land as a commit before any
   implementation.

2. **Worker alias resolver** (small, isolated). Just reads
   `data/card-aliases.json` and adds the 301-redirect path in
   `worker/index.js` for `/card/<id>` and the header on
   `/pdf/<id>.pdf`. Testable with a fake aliases file. Deployable
   today even with an empty aliases file — does nothing until the
   file has rows.

3. **`scripts/tranche_diff.py`** (the biggest piece). TDD'd against
   synthetic manifest pairs covering all three classes. Output
   schema validated by a small JSON schema file. Includes the
   title-continuity heuristic with all four rules.

4. **`pursue scrape approve` CLI + scrape-gate enforcement**. Adds
   the approval log and the refusal-to-proceed behavior.

5. **Post-scrape tampering audit**. Runs as a final step in
   `pursue scrape run` after a successful scrape.

6. **Finds-citation CI test** — `tests/unit/test_finds_citations.py`
   asserts every `<Cite card="…" />` resolves.

7. **Ingest tranche `65572b38…`** using the new toolchain end-to-end
   as the first real exercise. Validate the alias resolver works,
   the report reads cleanly, and the audit passes.

## Operator decisions (resolved 2026-05-12)

1. **Heuristic aggressiveness.** Every Class C goes to manual
   operator review. No auto-approval rule is exposed. The human is
   the trust mechanism until a solid programmatic one exists.

2. **Old card_id preservation.** Old card_ids continue to resolve
   forever via alias chain. Old R2 keys are append-only. Hash-prefix
   collisions are not a concern at this corpus scale (see
   "Preservation guarantee" section above). The aliases surface
   makes the rename relationship explicit per-card.

3. **Bandwidth budget for tranche_diff.** Acceptable. Operator has
   sufficient local storage. HEAD-pre-filter retained as an
   optimization but not a requirement.

4. **Alias surfacing.** Pill on the card detail page, no new
   navigation surface. Concretely:
   - `/card/<new_id>` renders a small pill near the title:
     **"Previously listed as `<old_id>` — `<old_title>`"** linking
     back to `/card/<old_id>`.
   - `/card/<old_id>` returns HTTP 301 to `/card/<new_id>` with a
     short interstitial banner: **"This card was re-cataloged on
     `<date>` as `<new_id>` — content unchanged (cryptographically
     verified)."** Banner shows briefly then auto-follows the
     redirect.
   - Both surfaces are self-documenting; no `/renamed` index page,
     no nav-bar entry.
   - Power-user filter on `/search` (e.g., `aliased:true`) is
     deferred; can add later if needed.

## Alias resolution on derived indexes (`/atlas`, `/search`, `/gallery`)

The embedding index, lexical search index, and gallery indexes
rebuild from the current manifest on each ingest, so they reflect
the new card_ids. Old card_ids effectively disappear from those
surfaces but stay reachable via direct URL + alias. This is the
intended behavior: the indexes show the current catalog state;
historical handles continue to resolve. Anyone holding a stale link
or citing an old card_id from a third-party context gets routed to
the right place via the worker resolver and the per-card pill.

## Out of scope for this plan

- Editorial rules for how finds entries should treat aliased cards
  beyond the resilience case (operator-curated)
- UI design for any `/renamed` surface (open question 4)
- Backfilling aliases for historical renames that pre-date this
  tooling — none are currently known (we only have the NASC-State
  byte-collision which the integrity layer caught manually)

## Estimated effort

- This plan + operator approval: ~1 hour
- Worker alias resolver (step 2): ~2 hours TDD'd + reviewer cycle
- `tranche_diff.py` (step 3): ~4-6 hours TDD'd
- Scrape gate + approval CLI (step 4): ~2 hours
- Post-scrape audit (step 5): ~1 hour
- Citation CI test (step 6): ~1 hour
- First real ingest exercise (step 7): operator-driven, ~1-2 hours

Total: roughly one focused day, two if reviewer cycle finds anything.
