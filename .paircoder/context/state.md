# Current State

> Last updated: 2026-05-21 (Sprint 4i #2 + #3 + #4 + #9 + #10 all landed locally with TDD. Awaiting commit + push.)

## 2026-05-21 — Sprint 4i batch 1 (5 of 10 items landed locally)

### Items closed this session

- **#3 repo cleanup**: deleted stale local branches `sprint-4a-integrity-seo` + `sprint-4b-polish-and-ops`; `git remote prune origin` clean.
- **#2 OCR envelope-artifact parser root-cause fix**: third-tier fallback `recover_envelope()` after `json.loads` → `find_text_json_object` → envelope-recovery → raw-text default. Detects the canonical envelope via regex (mirrors `scripts/repair_altered_ocr_envelopes.py`), extracts inner text, expands `\n` / `\t` / `\r` / `\"` / `\\`, pulls confidence from the well-formed tail. Affects every future OCR run.
- **#9 apollo-17.png rebuild**: ran `python scripts/build_finds_og_images.py`; the formerly-failing test (and 20 sibling finds PNGs that were also stale relative to the renderer) now byte-match the committed images.
- **#4 real API token tracking**: new `ocr_image_with_usage()` parallel API in `pursue_index.ocr.llm` returns `(text, conf, usage_dict)`. Cache hits return all-zeros usage. `scripts/reocr_altered.py` swapped from the hardcoded 1500/600 estimate to real SDK numbers via this seam. `ocr_image()` preserved as thin delegate.
- **#10 lint nits**: ruff clean on Sprint 4h scripts (`scripts/reocr_altered.py`, `scripts/_reocr_helpers.py`, `scripts/build_altered_diffs.py`). Renamed `CostCapExceeded` → `CostCapExceededError` (N818). Sorted `__all__`. Fixed `Callable` import (UP035, now from `collections.abc`). Consolidated 3 split-by-isort `from _reocr_helpers import ...` blocks back into one with `# noqa: E402, I001`. Replaced pre-existing `×` → `x` in llm.py docstring (RUF001).
- **Architecting**: when the parser fix pushed `llm.py` over the 15-function arch ceiling (16), extracted `_NOMINAL_CONFIDENCE`, `ZERO_USAGE`, `_ENVELOPE_*_RE`, `find_text_json_object`, `recover_envelope`, `parse_response`, `extract_usage` to a sibling `src/pursue_index/ocr/_llm_parsing.py` module. `llm.py` now 243 lines / 12 functions; `_llm_parsing.py` clean (no violations).
- **Social-platform scrub** (operator-directed pre-sprint chore): scrubbed Reddit/HN/Mastodon/Bluesky from comments + planning docs + .gitignore (`docs/launch/hn-post.md`). Twitter references kept only where they name the literal HTML meta-tag spec (`twitter:card`, `twitter:image:alt`, etc. — code requirement). 9 files touched.

### Verification

- Full python suite: 723 passed, 0 failed (was 720 + 1 pre-existing apollo failure; the 1 red is now green).
- Arch check: 0 errors on every modified file. Warnings only on file-size (`llm.py` 243, `test_ocr_llm.py` 462, `reocr_altered.py` 315) — all well under the 400/600 error thresholds.
- Ruff: clean on Sprint 4h scripts + `llm.py` + `_llm_parsing.py`.

### Still open in Sprint 4i

Items #1 (OCR retry on the 2 content-filter cards — needs operator-attended dispatch + ~$2-5 spend), #5 (OCR cache shareability — `data/ocr/.llm-cache` is operator-local), #6 (JSON-LD on `/altered/[card_id]` pages), #7 (CI size gate on `altered-diffs.json`), #8 (Archive_key format assertion in `fetch_r2_pdf`).

## 2026-05-20 — SESSION HANDOFF

### Sync state at handoff

- Branch `main` at `c19acdc` (envelope-artifact hotfix); up to date with `origin/main`
- Working tree clean
- 0 open PRs on BPSAI/pursue-index
- **2 stale local branches** with `[gone]` upstreams — first cleanup task next session:
  ```
  git branch -D sprint-4a-integrity-seo sprint-4b-polish-and-ops
  ```
- Sprint 4d/4e/4f/4g/4h all merged this session; all surfaces live on `https://pursueindex.com`

### Open issues from this session (Sprint 4i candidates, priority-ordered)

| # | Item | Estimated effort | Notes |
|---|---|---|---|
| **1** | **OCR retry on the 2 content-filter cards** (`7d58f0cac741650a` p87-184, `f85532f0514320be` p74-205) via `o4-mini` (frontier backstop) or `GLM-OCR` (local from VLM bake-off; ~$0). Each card has ~130 pages remaining. | 1-2h attended + ~$2-5 if o4-mini | Sprint 4h's per-card OCR INCOMPLETE banner will resolve once cleaned diff regenerates. Use `scripts/reocr_altered.py` with a new `--engine o4-mini` flag, OR write a tiny one-shot. |
| **2** | **Root-cause parser fix** for the envelope artifact — `pursue_index/ocr/llm.py::_parse_response`. Should detect malformed-but-recoverable JSON envelopes (unescaped inner quotes) and fall back to regex extraction. Affects every future OCR run, not just Sprint 4h. | 1-2h | The hotfix script (`scripts/repair_altered_ocr_envelopes.py`) is a post-processing pass; this is the upstream fix that prevents recurrence. |
| **3** | **Repo cleanup**: delete stale local branches above + `git remote prune origin` (low-risk; just hygiene) | 5 min | First action next session per operator note |
| **4** | **Actual API token tracking** in `scripts/reocr_altered.py` — currently uses hardcoded 1500/600 estimate (~21% under-counts vs reality). nayru flagged on PR #72. Requires `pursue_index.ocr.llm.ocr_image` to return usage. | 30 min |
| **5** | **OCR cache shareability** — `data/ocr/.llm-cache` is operator-local (`/mnt/nas/...`); a fresh checkout / CI runner would re-spend the $46. vaivora flagged on PR #72. Either commit the cache or document the NAS-pinning env var. | 30 min |
| **6** | **JSON-LD on `/altered/[card_id]` pages** — currently no structured data on the diff pages. Other surfaces have it. Discoverability polish. | 30 min |
| **7** | **CI size gate on `altered-diffs.json`** — laverna P3; current 9.3MB is fine, but if a future tranche triples the corpus the Astro build could OOM. | 15 min |
| **8** | **Archive_key format assertion** in `fetch_r2_pdf` — laverna P3 defense-in-depth. Currently no app-layer validation before boto3 get_object. | 15 min |
| **9** | **Pre-existing `apollo-17.png` test failure** on main — committed PNG is stale relative to the renderer. Verified failing pre-Sprint-4d. Just needs `python scripts/build_finds_og_images.py` + commit. | 5 min |
| **10** | **Lint nits** from triad: unused imports, sort `__all__`, ruff UP035 `Callable` import, ruff N818 rename `CostCapExceeded` → `CostCapExceededError`, etc. | 30 min batch |

### Other-project backlog (review next session before picking next sprint)

After Sprint 4i housekeeping, the backlog review should consult:

- **`.paircoder/plans/`** — local plans:
  - `altered-ocr-diff.md` (Sprint 4h plan — now complete)
  - `autonomous-finds-pipeline.md` — multi-week, ongoing API spend per tranche
  - `incidents-map-clustering.md` — net-new `/map` surface, geographic browse
  - `pursue-vision-augment.md` — Phase 2 VLM extraction (post-Sprint-6 work)
  - `clean-quality-review.md`, `review-correct.md`, `black-vault-reference.md`, `display-date-curation.md`, `diff-page-arbitrary-pair-selection.md`
- **`pursue-opsec-staging/findings/`** — cross-cutting:
  - `2026-05-18-tier2-registry-signing-rfc.md` (Sprint 4e implementation; recommendation approved + landed)
  - `2026-05-18-vlm-bakeoff-final.md` (Sprint 6.1 — canonical operated VLM answer)
  - `2026-05-16-sprint-roadmap.md` (the multi-sprint roadmap; partially superseded by 4d-4h)

### Receipts-layer readiness

The receipts layer (Sprint 4g+4h) is live on prod:
- `/altered/` lists 79 cards
- `/altered/<card_id>/` per-card sentence-level diff
- `/archive/<sha>.<ext>` content-addressed preserved bytes
- Per-card banner on `/card/<id>/`

**Recommended QA action: manually inspect the top-5 substantive-diff cards** to confirm the diffs are real content changes (not artifacts). After the envelope hotfix, `8d0b85ce46109d06` dropped from 777/818 → 576/555 word delta — meaning real diff was inflated 35% by the artifact. Other affected cards likely similar.

Substantive-diff candidates (need eyeball verification):
- `13f86e95aed52840` (269pp, 39k/42k words delta — Section 6 re-pinned card)
- `e897e67f95bc1e1b` (107pp, 35k/37k)
- `8bfd94484138d59b` (246pp, 24k/28k)
- `4844321219e306af` (167pp)

After Sprint 4i #1 + #2 land (content-filter retry + parser root-cause), all 79 diffs will be fully clean.

## 2026-05-20 — Sprint 4h MERGED (PR #72 → `a7b3dae`)

## 2026-05-20 — Sprint 4h MERGED (PR #72 → `a7b3dae`)

The receipts layer for the May-14 redaction class. Sprint 4g made the bytes reachable; Sprint 4h shows the text changes. Audit's deferred P2.6 promoted to ship.

### What landed

| Layer | File | Notes |
|---|---|---|
| OCR pipeline | `scripts/reocr_altered.py` + `_reocr_helpers.py` | Sonnet 4.6 single-pass via existing `pursue_index.ocr.llm`. 8-way concurrency. Resume-aware + cost-capped. |
| Diff builder | `scripts/build_altered_diffs.py` | Sentence-level via difflib. Symmetric coverage classification (complete / partial / post_extended). Pins pre-edit OCR source sha256 in `_meta` block. |
| Diff page | `web/src/pages/altered/[card_id].astro` | Side-by-side red strikethrough / green underline. OCR INCOMPLETE banner for partial cards. |
| Cross-links | `/altered` table "text diff →" + card banner "See exact text changes →" + llms.txt entries | Discoverability |
| Data | `data/altered-ocr/<79 dirs>/pages.jsonl` (6.4 MB) + `web/src/data/altered-diffs.json` (9.3 MB) | Committed for reproducibility |

### OCR run (operator-attended, 2026-05-20T20:17-22:23 UTC)

- 79 cards selected, 3,425 OCR calls, **$46.24 total spend** (well under $90 cap)
- 77 clean + 2 content-filter trips (`7d58f0cac741650a` truncated at page 87/184; `f85532f0514320be` at 74/205) → Sprint 4i follow-up via o4-mini backstop
- Per-card OCR INCOMPLETE banner correctly surfaces truncation as truncation, not redaction

### Headline diffs surfaced

| Card | Removed | Added | Pages |
|---|---|---|---|
| `13f86e95aed52840` | 39,291 | 42,116 | 269 |
| `e897e67f95bc1e1b` | 35,367 | 37,308 | 107 |
| `8bfd94484138d59b` | 24,677 | 28,505 | 246 |
| `7d58f0cac741650a` (partial) | 37,125 | 40,224 | 87/184 |
| `0d7a23b29e6de1bf` (FBI Photo B008, -78.7% file shrink) | 16 | 12 | 1 |

### Review cycle

- **Codex initial** on `a203ff8`: 1 P2 (post-only pages dropped from diff)
- **In-house triad** (nayru + laverna + vaivora): 3 H + 6 M + 15 L findings
- **Fix-pass #1** (`69bed87`): H1 arch error on `build_card_diff`, H2 dead test code, H3 post_extended case (Codex P2 + triad H3 both), H4 pages-cleaned.json freshness pin via sha256, M1 dropped fsync, M2 warn on edge case
- **Codex on fix-pass**: 1 new P1 (torn-write trap — every rerun re-spends full budget)
- **Fix-pass #2** (`2c6fecd`): `truncate_jsonl_to_valid_prefix` helper; `ocr_card` repairs before resuming. 5 new tests pin the repair contract.
- Squash-merged as `a7b3dae` per operator direction (no further Codex loop).

### Test count

- Sprint 4h: 0 → 37 (+14 reocr + 18 diff builder + 5 torn-write repair)
- Full python suite: 700 → 705 passed
- Pre-existing apollo-17.png failure on main: unchanged, Sprint 4i follow-up

### Deferred to Sprint 4i (per triad)

- Retry the 2 content-filter cards via o4-mini backstop (Sprint 4h banner explains the gap; ship-ready, Sprint 4i polishes)
- Actual API usage tracking (vs current hardcoded 1500/600 token estimate) — needs change to canonical `pursue_index.ocr.llm` to return usage
- OCR cache shareability (currently operator-local at `/mnt/nas/...`; future operators re-pay $46)
- Keyed-per-card altered-diffs JSON (current 9.3 MB SSR-imported is fine for now)
- JSON-LD on diff pages (discoverability polish)
- Archive_key format assertion at `fetch_r2_pdf` (defense-in-depth)
- CI size gate on altered-diffs.json
- Lint nits (unused imports, sort __all__, etc.)
- Pre-existing apollo-17.png stale test failure

### Integrity-receipts story

The four sprints (4d auto-closer + 4e tier-2 signing + 4f AUD type + 4g altered surface + 4h OCR diff) together complete the integrity-receipts story end-to-end.

Notable spot-cases for QA / citation work: the FBI Photo B008 diff at `/altered/0d7a23b29e6de1bf/` (78.7% file shrink, tabular data shifted) and the larger redaction events (`13f86e95aed52840` with 39k words removed).

## 2026-05-20 — Sprint 4g MERGED (PR #71 → `b339d1e`)

## 2026-05-20 — Sprint 4g MERGED (PR #71 → `b339d1e`)

Pre-launch integrity audit found that 79 cards whose upstream bytes were silently re-published under the same card_ids (mostly 2026-05-14) were unreachable from any user-facing surface — visitors saw post-edit PDF in the iframe + pre-edit OCR text below + zero notice. `worker/pdf.js` even claimed `Cache-Control: immutable`, which had been quietly lying since May 14.

### What shipped (4 phases)

| Phase | Surface |
|---|---|
| 1 | `worker/pdf.js::tryHandleArchiveRoute` — new `/archive/<sha>.<ext>` route. Content-addressed (honestly immutable). Strict 64-hex sha + extension allowlist (pdf/png/jpg/jpeg/gif/webp/mp4). 16 new worker tests. Path-traversal hardened against encoded slashes, `..` segments, dotfiles, multi-dot, etc. |
| 2 | `worker/pdf.js::baseHeaders` (renamed `buildHeaders`) — `/pdf/<card_id>.pdf` switched from `max-age=31536000, immutable` to Sprint 2.1 worker policy (`max-age=3600, stale-while-revalidate=86400`). `immutable` token explicitly removed (test asserts `doesNotMatch(/immutable/)`). |
| 3 | `web/scripts/build_byte_history.mjs` + `web/src/data/byte-history.json` — build-time card_id → newest-first byte-history map (multi-sha cards only). Card-detail page renders amber "BYTES CHANGED UPSTREAM" banner above iframe linking to preserved version(s) via /archive/. |
| 4 | `web/src/pages/altered.astro` — listing page with table (size delta, dates, archive link) + JSON-LD ItemList for crawler discoverability. `/removed.astro` header copy fix. Nav extension. `web/src/lib/byte-display.ts` + `altered-helpers.ts` extracted with pinned tests. |

### Cycle (3 Codex review rounds + 1 in-house triad)

- **Codex initial** on `577ee7a`: 0 blockers.
- **Triad (nayru + laverna + vaivora)**: 5 M1 findings + 1 vaivora P1.1 operator-decision flag. Bundled fix-pass `40cf80f` applied 4 M1s (anchor mismatch in /removed, 78→79 comment drift, helper extraction × 2). vaivora P1.1 (AI bot policy on /archive/*) explicitly left as-is per operator direction.
- **Codex on `40cf80f`**: P1 — registry has 28 .mp4 archive_keys; 9 of 79 multi-sha cards point at .mp4; without allowlist entry those /altered + banner links returned 400. Fix `79cd21e`: added `mp4 → video/mp4` + test. (+1 worker test → 153.)
- **Codex on `79cd21e`**: P2 — sort comparator `(a.key < b.key ? 1 : -1)` never returned 0, violated sort-comparator contract; ES2019+ stable-sort masked it but inter-runtime stability not guaranteed. Fix `b862038`: explicit equality branch with deterministic byte_sha256 / title tie-breaker; tests pin the contract. byte-history.json regenerated (8-line diff, deterministic re-order among entries with tied fetched_at; `is_current` semantics preserved).
- Merged as `b339d1e` per operator direction (no further Codex loop).

### Final test deltas

- Worker: 137 → 153 (+16 from archive.test.js + the MP4 test).
- Web: build_byte_history.test.mjs +8, altered-helpers.test.ts +6, byte-display.test.ts +12. Astro build 183 pages (was 182, +1 for /altered).
- Python: 669 passed; 1 pre-existing failure (apollo-17.png stale; unrelated to 4g — flagged for separate follow-up).
- arch check: clean on every modified file.

### Live spot-check (post CF Pages deploy)

Verify after deploy: hit `https://pursueindex.com/altered/` (should list 79 cards) and a sample affected card (e.g. `/card/0d7a23b29e6de1bf/` FBI Photo B008 — should render amber "BYTES CHANGED UPSTREAM" banner with `-78.7%` delta + link to `/archive/cae6a62245153fd1...pdf`).

### Deferred (per audit's P2, all operator-attended or follow-up)

- OCR labeling on cards (~1h).
- OCR re-run on the 79 new bytes for side-by-side text-diff page (~$0.20-15 spend + 4-6h impl; attended).
- /removed copy update reflecting that two entries' content was re-published under new card_ids (editorial pass).
- nayru L1 polish items (export cache constants, portable main-guard, Vary: Range, prebuild ordering comment, /altered in llms.txt) — defer to a separate sprint or punt entirely.
- vaivora P1.1 (Disallow /archive/ for AI_ALLOW search bots) — operator chose to leave as-is.
- Pre-existing apollo-17.png test failure on main — file separately as `chore(finds): rebuild apollo-17.png`.

## 2026-05-20 — Sprint 4f MERGED (PR #70 → `32ad9f5`)

## 2026-05-20 — Sprint 4f MERGED (PR #70 → `32ad9f5`)

AUD asset type support added after upstream relabeled the NASA Gemini 7 Audio Excerpt card (card_id `167f6a21c7238d0c`) from VID → AUD in tranche f75e2f7. The parser only accepted PDF/VID/IMG so it silently skipped the row, making the initial tranche_diff report a false-positive "removal". Post-merge, the diff correctly reads: 0 removed, 1 field-only-change (asset_type: VID → AUD).

### Cycle (faster than 4d/4e — no Codex back-and-forth)

- **Initial commit `12f9c38`** — parser core (types.py + normalize.py) + downstream surfaces (downloader defensive .get(), CardExplorer, GalleryIsland, CardOcrIsland, card-detail page).
- **Codex initial review** — one P2 (already addressed in concurrent triad fix-pass; comment was anchored to the latest commit but referred to pre-fix-pass state).
- **In-house triad (nayru + laverna + vaivora) caught 5 P1 consumer-side gaps**: types.ts mirror, gallery.astro filter, [card_id].astro TYPE_COLORS, TimelineIsland.tsx ALL_TYPES, test_downloader_asset_path AUD-with-url test coverage gap. Bundled fix-pass `8f02e48`.
- **Codex re-review on `8f02e48`**: "Didn't find any major issues. More of your lovely PRs please." Clean.
- Squash-merged as `32ad9f5`.

### Surfaces touched

| Layer | Files |
|---|---|
| Parser | `src/pursue_index/scrape/{types,normalize}.py` — AUD added to Literal + accepted set; dual semantics on `dvids_video_id` documented |
| Downloader | `src/pursue_index/download/downloader.py` — defensive `.get()` on type→dir map (fail-closed for unknown future types) |
| TypeScript mirror | `web/src/data/types.ts` |
| Page filters | `web/src/pages/gallery.astro` allow-list |
| Page rendering | `web/src/pages/card/[card_id].astro` — `isAudio` flag + `dvidshub.net/audio/embed/<id>` iframe + TYPE_COLORS amber entry |
| Components | `CardExplorer.tsx` (TYPE_TONE + filter), `GalleryIsland.tsx` (VIDEOS-lane predicate + waveform tile icon + counter), `CardOcrIsland.tsx` (AUD empty-state copy), `TimelineIsland.tsx` (ALL_TYPES) |
| Tests | `tests/unit/test_normalize.py` (AUD accept + PHOTO rejection); `tests/unit/test_downloader_asset_path.py` (new file, 6 tests pinning fail-closed contract) |
| Tranche-diff | `.paircoder/plans/tranche-diff-f75e2f7de0ff.{json,md}` — committed refreshed diff |

### Deferred with rationale

- **laverna P2-001** (numeric-only validation of `dvids_video_id` before URL interpolation) — pre-existing parity issue with VID embed, not a 4f regression. Should land as a separate follow-up that defangs both embed paths together.
- **nayru P2 polish** — non-blocking naming + constant-extraction items.

### Test count (final)

- Python: 663 → 670 (+7 across 4f).
- Web: 6/6 pass + lib clean.
- Worker: 137/137 pass.
- Astro build: 182 pages, ~6.8s.
- arch check: clean on every touched file.

## Tier-2 setup status (post-Sprint-4e operator action items)

All complete:

- ✅ Signing key (ed25519, `~/.ssh/pursue_signing`) generated + uploaded to GitHub Settings → SSH and GPG keys → **Signing keys** (via `gh auth refresh -s admin:ssh_signing_key && gh ssh-key add ... --type signing`).
- ✅ `OPERATOR_ALLOWED_SIGNERS` repo secret set (verified via `gh secret list`).
- ✅ Git configured for SSH signing (`gpg.format=ssh`, `user.signingkey`, `tag.gpgsign=true` globally).
- ✅ `docs/allowed-signers.txt` populated with operator pubkey (commits `e5be0f4` + `2ec89de`).
- ✅ Baseline tag signed + pushed: `registry-root-2026-05-20-1643-baseline` over commit `e5be0f4`. Local `git tag -v` returns "Good git signature".
- ⏸️ Optional: tag-pattern protection ruleset in GitHub Settings → Rules → Rulesets (defers force-deletion of `registry-root-*` tags).

## Real-world dry-run queued (Sprint 4d + 4e + 4f end-to-end)

Tranche `f75e2f7de0ffb79622fbb005e436558f6581573c5370df4b0185f6a800226543` (NASA Gemini 7 audio reclassification) is detected upstream — issue #69 is open. Whenever the operator runs `pursue ingest run` to promote it, three sprints exercise simultaneously for the first time against a real event:

1. **Sprint 4d auto-closer**: should close issue #69 once the promote commit lands on main.
2. **Sprint 4e on-promote workflow**: should re-derive the registry root, match the bumped `data/registry-root.txt`, return green.
3. **Sprint 4e signing-stale lane (daily verify)**: next 06:07 UTC tick should detect that current root no longer matches the latest signed tag → file `signing-stale` issue → operator signs a fresh tag → next cron resolves.
4. **Sprint 4f rendering**: NASA Gemini 7 card displays via `dvidshub.net/audio/embed/1006119`, amber badge, AUD filter on /explore + /gallery VIDEOS lane + /timeline.

vaivora flagged one item to tail during the dry-run: the asset_type mutation (VID → AUD) may surface a different auto-closer log path than card-id-only mutations. Worth watching the workflow log on first promote.

## 2026-05-19 — Sprint 4e MERGED (PR #68 → `b76c2c8`)

Sprint 4e went through THREE Codex review cycles (initial + 2 fix-pass rounds) before clean:

- **Initial review** caught P1 #1 (verify not bound to current registry commit) + P1 #2 (trust anchor in mutable repo state).
- **Fix-pass #1** (commit `f2f6e7d`) addressed those + the in-house triad (nayru/laverna/vaivora) findings — RFC 6962 domain separation, freshness binding, bot-writer root refresh, manifest in path filter, allow_nan, encoding=utf-8, etc.
- **Codex P1 #3** then surfaced: `gh api .verification.verified` only confirms "valid against ANY GitHub-registered signing key" — a repo:write attacker with their *own* registered Signing key satisfies that check.
- **Fix-pass #2** (commit `a4fc10e`) pinned trust to a GitHub Actions secret `OPERATOR_ALLOWED_SIGNERS`. Only repo admin/maintain can modify it.
- **Codex P2s** then surfaced two stale-doc bugs in the runbook (still referenced "GH-API anchor" + rotation playbook only updated allowed-signers.txt, not the secret).
- **Fix-pass #3** (commit `d5ae213`) corrected those.
- Squash-merged as `b76c2c8` per operator direction (no post-merge review cycle).

### Files on main

- `scripts/registry_root.py` — RFC 6962 Merkle root over canonical-JSON registry rows.
- `scripts/verify_registry_root.py` — re-derive + compare to root.txt + divergence locator.
- `.github/workflows/registry-root-on-promote.yml` — push trigger, allowed to fail red.
- `.github/workflows/verify-assets-daily.yml` (modified) — adds tag-verify step against `OPERATOR_ALLOWED_SIGNERS` secret + freshness binding + signing-failure / signing-stale issue lanes.
- `.github/workflows/poll-pursue.yml` (modified) — commit step refreshes root in lockstep.
- `docs/allowed-signers.txt` — reader-convenience documentation (not the CI trust anchor).
- `docs/runbooks/registry-root-signing.md` — full operator playbook.
- `data/registry-root.txt` — baseline `994e9edac7396c1d03bba3b0d17bfabe1f04bf1d51c543807010da1a3bb3369d` (230 rows).
- `data/registry-root-manifest.txt` — tab-separated receipt.

### Dark-code posture per [[feedback_ship_wired_and_validated]]

The on-promote workflow is wired and immediately functional (verifies root-file freshness on every registry push). The tier-2 signature lane is in `signing_state=bootstrap` mode until the operator completes setup. **Operator action items below.**

### Test count (final)

- Python suite: 574 → 663 (+89 over Sprint 4d + 4e combined).
- arch check: 0 errors. File-size warnings only on `registry_root.py` (224 lines) and `verify_registry_root.py` (213 lines) — under 400 error threshold.

## 2026-05-19 — Sprint 4e PR #68 2nd fix-pass (Codex P1 #3)

After the first fix-pass merged the GH-API trust anchor, Codex re-reviewed and surfaced a real residual gap: `gh api .verification.verified` returns true for ANY tag signed by ANY GitHub-registered Signing key — a repo:write attacker with their own registered key can satisfy that check.

Fix: trust anchor now sources from a GitHub Actions secret `OPERATOR_ALLOWED_SIGNERS` containing the operator's pubkey in allowed-signers format. Verify step writes the secret to a runner-local tmp file at job time and runs `git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=<tmp> tag -v <latest>`. The secret is modifiable only by repo admin/maintain (not by repo:write contributors) — that's the security boundary tier-2 cares about.

New state `signing_state=unconfigured` distinct from `bootstrap`: bootstrap = no signed tag yet; unconfigured = signed tag exists but secret isn't set. Both exit 0 with notice/warning.

Updates:
- `verify-assets-daily.yml` — swap `gh api` for secret-pinned `git tag -v`.
- Runbook + `allowed-signers.txt` comments document the new trust anchor + add a setup step for the secret.
- Tests pin the new shape: `OPERATOR_ALLOWED_SIGNERS` env, secret materialized to tmp, no `gh api` trust path.

Python suite: 662 → 663 (+1). All workflow tests green.

## 2026-05-19 — Sprint 4e PR #68 fix-pass (bundled, post-triad-review)

## 2026-05-19 — Sprint 4e PR #68 fix-pass (bundled, post-triad-review)

Codex came back with two P1s in the same vein as findings my own dispatched triad surfaced; bundled everything into a single fix-pass commit per [[feedback_bundled_commits]].

### Codex P1 findings (both applied)

- **P1 #1** — Bind verify to current registry commit. The daily verify previously passed if ANY `registry-root-*` tag had a valid signature, even if the signed tag pointed at an older root than HEAD. New: extract `git show <tag>:data/registry-root.txt` and compare to current HEAD's root; on mismatch, emit `signing_state=stale` and file a `signing-stale` issue (distinct from `signing-failure`).
- **P1 #2** — Move trust anchor out of mutable repo state. `docs/allowed-signers.txt` is repo-tracked and writable by anyone with repo:write — exactly the threat tier-2 exists to detect. Switched the CI lane to `gh api repos/.../git/tags/$tag_object_sha --jq '.verification.verified'`. Trust anchor is now GitHub's profile-level Signing keys, which a repo:write attacker cannot modify. `docs/allowed-signers.txt` reduced to reader-convenience docs only.

### nayru / laverna / vaivora bundled (15 applied, 3 deferred)

- **nayru H1.1 + laverna P1** — RFC 6962 domain separation (`0x00` prefix for leaves, `0x01` for internal nodes). Defeats the Bitcoin CVE-2012-2459 2nd-preimage class. New tests prove `[a,b,c]` and `[a,b,c,c]` now produce different roots. Live baseline root changed: `913e37d224dc...` → `994e9edac739...`.
- **nayru H1.2 + vaivora H1** — Bot writers refresh root in lockstep. `poll-pursue.yml` + `verify-assets-daily.yml` commit steps now run `python scripts/registry_root.py` before staging the registry, and stage `data/registry-root.txt` + `data/registry-root-manifest.txt` alongside. The on-promote workflow stays green on bot-driven appends; the operator sees a `signing-stale` issue prompting them to sign a fresh tag.
- **nayru M1.1** — Missing registry file emits actionable `::error::registry file not found at <path>` instead of stack trace.
- **nayru M1.2** — Malformed `--signed-source` emits `::warning::` + skips divergence locator instead of crashing.
- **nayru M1.3** — `null` `fetched_at` maps to `(unknown)` instead of literal `"None"`.
- **nayru M1.4** — `encoding="utf-8"` explicit on all `read_text` / `write_text` in both scripts.
- **nayru M2.1** — `_read_registry_rows` renamed `read_registry_rows` (publicly importable).
- **laverna P2** — `allow_nan=False` rejects `NaN`/`Infinity` at canonicalization time.
- **vaivora M1** — `data/registry-root-manifest.txt` added to on-promote workflow's path filter.

### Not applied (deferred with rationale)

- laverna P2 (bootstrap-pending issue) — runbook already directs the operator clearly; one-time setup. Issue-spam not worth the noise.
- nayru M1.5/M1.6 (additional divergence + truncated-hex tests) — current coverage is sufficient for the integrity-critical paths; defer.
- vaivora M2 (`pursue verify registry-root` CLI subcommand) — carry-over; defer until the operator has run the manual `python scripts/verify_registry_root.py` path enough to feel CLI ergonomics.
- nayru M2.2 (fsync atomic write) — matches existing project precedent; no action.
- nayru M2.3 (RFC 8785 docstring tightening) — applied (RFC 8785 reference reframed to subset claim).

### Test count delta (fix-pass)

- python suite: 653 → 662 (+9).
- arch check: 0 errors on all files; 2 file-size warnings (`registry_root.py` 224 / `verify_registry_root.py` 213) — well under 400 error threshold.

## 2026-05-19 — Sprint 4d MERGED (PR #67 → `48ccd51`)

## 2026-05-19 — Sprint 4d MERGED (PR #67 → `48ccd51`)

Codex re-review on the fix-pass found no further issues. PR squash-merged to main; branch `sprint-4d-tranche-autoclose` deleted locally + remotely; `git remote prune origin` clean.

### Files on main

- `scripts/close_tranche_issues_on_promote.py` (339 lines)
- `.github/workflows/close-tranche-on-promote.yml` (74 lines)
- `tests/unit/test_close_tranche_issues_on_promote.py` (548 lines, 28 tests)
- `tests/unit/test_close_tranche_on_promote_workflow.py` (98 lines, 7 tests)

### Dark-code posture per [[feedback_ship_wired_and_validated]]

The workflow is wired (push trigger + `data/manifests/latest.json` path filter + correct permissions + SHA-pinned actions) but has NOT yet produced output. **Trigger:** the next time the operator runs `pursue ingest run` and pushes the resulting manifest change to main, the workflow fires. There are no currently-open `tranche-detected` issues (last two — #63 + #64 — were manually closed in the prior session), so the first live firing will surface a `::notice::no open tranche-detected issue matches promoted sha <short>; nothing to close` log line. That's the expected baseline; the auto-close branch will exercise on the FIRST promote that lands while a `tranche-detected` issue is open (i.e., the operator runs `pursue ingest run` for a tranche surfaced by the 30-min poll cron during the same session window).

### Validation chain so far

- 35 new tests cover every branch of main() (happy path, no-match, missing manifest, corrupt manifest, gh-absent, list-rc-nonzero with stderr, list-rc-nonzero with empty stderr, close-rc-nonzero, comment-rc-nonzero, multi-match, non-int issue number, list+close unbounded-stderr truncation).
- Producer/consumer contract pinned by `test_parse_new_sha_round_trips_changed_issue_body` (links `_poll_gh_io.changed_issue_body` ↔ `parse_new_sha_from_body`).
- Workflow shape locked: trigger narrowing, permissions, env exports, SHA-pinning, concurrency `cancel-in-progress: False`, script invocation path.

### Review cycle landed (full file-list pass per [[feedback_review_cycle_by_filelist]])

- **Codex** initial: P1 (gh list failures masked) + P2 (close rc ignored). Both fixed.
- **Codex** re-review (after fix-pass): no further findings. Clean.
- **nayru**: 1 arch error (H1) + 2 P1 quality (H2/H3) + 4 P2 (M1/M3/M4/M5) + 1 L3 polish. All 8 applied.
- **vaivora**: 1 H (round-trip test gap) + 1 M (workflow header docs). Both applied.
- **laverna** (re-launched after first run timed out): 1 P1 (SEC-P1-001 stderr truncation per SEC-003 pattern). Applied. 2 P2 deferred with rationale (`GITHUB_REPOSITORY` shape validation, rate-limit back-off).

### Test count delta (final)

- Python suite: 574 → 610 (+36 from Sprint 4d).
- arch check: 0 errors, 1 file-size warning on the script (339 vs 200 warn / 400 error).

## 2026-05-19 — Sprint 4d PR #67 second fix-pass (laverna stderr truncate)

After the first fix-pass push, re-launched laverna with a tighter brief (it had timed out mid-investigation on the first pass). Single P1 returned:

**SEC-P1-001** — gh stderr surfaced unbounded in `::warning::` annotations against the repo's own SEC-003 precedent (`scripts/_poll_gh_io.py::truncate_error`, 500-char cap). gh "hint" lines can echo bearer-token fragments on auth failure; an unbounded surface compounds rate-limit storms.

Applied as a separate small commit (not bundled with the prior fix-pass — that commit was already pushed and Codex-rereview-requested):

- `from _poll_gh_io import truncate_error` via the established sys.path manipulation pattern (mirrors `r2_verify_preserved.py:58-63`).
- Three call sites wrapped: `GhCommandFailed` constructor in `_list_open_tranche_issues`, comment-failed warning, close-failed warning.
- Two new tests pin the truncation behavior: 2000-char stderr → ≤700-char warning line + explicit `...[truncated]` marker.

Test count: 41 → 43 on the Sprint 4d modules; python suite 608 → 610. arch check clean.

P2 findings (deferred per laverna): `GITHUB_REPOSITORY` shape validation (narrow surface; runner-controlled today); rate-limit back-off (annotation-log only, not a vulnerability).

## 2026-05-19 — Sprint 4d PR #67 fix-pass (bundled)

Per [[feedback_bundled_commits]], one commit on top of `5bb7f8e` covering Codex P1/P2 + nayru/vaivora findings. (laverna timed out mid-investigation; nayru's review covered the security-adjacent concerns — command construction via list-of-args, permission scoping, action-pinning — at sufficient depth to proceed.)

### Codex findings applied

- **P1** — `gh issue list` failures no longer masquerade as no-match. New `GhCommandFailed` exception; main() catches it with a distinct `::warning::gh issue list failed; skipping auto-close: rc=N: <stderr>` line.
- **P2** — `_close_with_comment` now returns `bool` based on actual rc of both `gh issue comment` and `gh issue close`. main() suppresses `::notice::closed` when either fails. Comment failure short-circuits (does NOT proceed to close, avoiding orphaned-close).

### nayru P1 + P2 findings applied

- **H1** (arch error) — extracted `_close_matches(...)` helper. `main()` now 35 lines (was 53; ceiling 50). arch check clean.
- **H2** — `GhCommandFailed` message includes BOTH `rc=N` and stderr (or `(no stderr)` marker). Both diagnostic facts independent; both surface.
- **H3** — P1/P2 regression tests now pin stderr text (`"401"`, `"422"`, `"403"`, `"Bad credentials"`, `"Resource not accessible"`, `"already closed"`) reaches the log line. New `test_main_gh_list_nonzero_with_empty_stderr_still_includes_rc` covers the rc-only case.
- **M1** — workflow test asserts `cancel-in-progress is False` (pin against a future "make-it-snappy" flip).
- **M3** — `_GH_LIST_LIMIT` bumped 100 → 1000 with a comment explaining the ceiling (worst-case AFK-week posture).
- **M4** — `_close_with_comment` warnings now include `tranche <short>` so multi-match failure logs are self-describing.
- **M5** — non-int issue numbers emit `::warning::skipping issue with non-int number: <value!r>` instead of silent skip.
- **L3** — `test_parse_new_sha_picks_first_when_body_has_two` rewritten so both candidate lines start with `* new_sha:` (legitimately exercises first-match ordering, not just the `^` anchor).

### vaivora H/M findings applied

- **H1** — new `test_parse_new_sha_round_trips_changed_issue_body` test imports `scripts/_poll_gh_io.changed_issue_body()` and feeds its output into `parse_new_sha_from_body()`. Round-trip equality pinned for both the bootstrap and non-bootstrap body shapes. Closes the producer/consumer-coupled-but-not-locked gap.
- **M1** — workflow yaml header now documents the sibling-on-same-path (indexnow-after-deploy, fires concurrently, disjoint concurrency group; wayback moved off this trigger in Sprint 4c).

### Test count delta (fix-pass)

- New tests: 28 → 41 on the Sprint 4d modules (+13 across both files); python suite 605 → 608.
- All 608 green. arch check: 0 errors, 1 warning (file size 321 vs 200 warn; well under 400 error).

### Not applied (notes only)

- nayru M2 (workflow uses `GH_TOKEN` not `token:` on checkout) — intentional asymmetry, no change.
- nayru L1 (regex anchor) — verified correct, no change.
- nayru L2 (`collections.abc.Callable`) — minor convention nit, deferred.
- vaivora M2 (concurrency disjointness with poll-pursue) — sha-match design is the load-bearing protection; documented in the round-trip test.
- vaivora L1 (sys.path manipulation) — matches established repo-wide pattern across 15+ test files.



## 2026-05-18 — Tier-2 registry-signing RFC

Drafted `pursue-opsec-staging/findings/2026-05-18-tier2-registry-signing-rfc.md` (466 lines). Threat model (T1-T4 in scope; byzantine operator out), four options surveyed (per-row sig / Sigstore / Merkle+git-tag / release-tag-only), cost-vs-coverage matrix, recommendation: Merkle root + operator-signed git tag. Implementation sketch (~270 LOC + 23 tests). Three operator decisions called out before any code lands. Committed to opsec-staging local-only (`53f8163`); not pushed pending operator skim of the recommendation.

## 2026-05-18 — Sprint 4d: auto-close tranche-detected issues on promote

Branch `sprint-4d-tranche-autoclose` (commit `281e81d`) pushed; PR #67 opened with `@codex review` requested.

### What shipped

- **`scripts/close_tranche_issues_on_promote.py`** (227 lines) — pure-stdlib + `gh` CLI. Reads `csv_sha256` from the promoted manifest, lists open `tranche-detected` issues via `gh issue list`, matches each body's `* new_sha: \`<sha>\`` line (precise regex; fails closed on format drift), comments + closes match(es). Every branch exits 0 — a parser hiccup must never fail the promote workflow.
- **`.github/workflows/close-tranche-on-promote.yml`** — `push` to main on `data/manifests/latest.json` + `workflow_dispatch`; `permissions: { issues: write, contents: read }`; SHA-pinned actions per SEC-001; concurrency group `close-tranche-on-promote`.
- **`tests/unit/test_close_tranche_issues_on_promote.py`** — 21 unit tests (manifest read 5, body parse 4, matcher 4, comment text 2, main() integration via `_run_gh` fake 6).
- **`tests/unit/test_close_tranche_on_promote_workflow.py`** — 7 workflow-shape tests (yaml parses, trigger narrowing, permissions block, env exports, SHA-pinning, concurrency group, script invocation).

### Approach decision (recorded for follow-up sessions)

State.md had offered "extend `pursue ingest run` OR companion GH workflow". Picked **companion workflow** because (i) the bytes landing on main define "promoted", not the CLI invocation; (ii) `GITHUB_TOKEN` already has `issues: write` — no operator-local `gh` auth or PAT needed; (iii) matches the existing post-deploy pattern (wayback / indexnow / cf-managed-bots-drift).

### Verification

- 28 new tests green (21 + 7); python suite: 574 → 602 (+28). Web + worker suites unchanged (no surface in those modules touched).
- `bpsai-pair arch check` clean — single `file too large` warning on the script (227 vs 200 warn threshold; 400 error threshold). Test files clean.
- PR #67: https://github.com/BPSAI/pursue-index/pull/67

### Operator-action items

None — Codex review will arrive on PR #67 in ~5 min. After merge, the next `tranche-detected` issue auto-closes when the operator promotes that tranche; until then, the workflow no-ops on every manifest change with a `::notice::` log.

## ✅ Session handoff — 2026-05-17 → 2026-05-18

**Clean handoff state — everything confirmed live and tested. Next session can pick up directly with Sprint 4d / 5 / 6.2.**

### Live on prod (verified via `curl https://pursueindex.com/`)

| Surface | Status | Verification |
|---|---|---|
| ItemList JSON-LD (158 ListItems for crawler-visible cards) | ✅ Live | `grep -o '"@type":"ListItem"' \| wc -l` → 158 |
| Dataset JSON-LD (Sprint 1 GEO foundation) | ✅ Live | 1 entry, schema.org/Dataset |
| Cache-Control on /_astro/* (Sprint 2.1 worker headers) | ✅ Live | `public, max-age=31536000, immutable` |
| CF Web Analytics beacon (Sprint 4a B5) | ✅ Live | token `28d5f461bce94463afa26c5d78e5517b` |
| IndexNow ownership file | ✅ Live | `https://pursueindex.com/3ac171e82c609affc9699ce12fbe5e71.txt` returns the key |
| HTML size 695 KB → 53 KB (Sprint 4b Theme F + fix-pass) | ✅ -92% | Confirmed via `curl ... \| wc -c` |
| Mobile Lighthouse 37-69 → 90-95 globally (Sprint 2 + 2.1) | ✅ Confirmed | All six baseline regions cleared targets |

### Sprints shipped this session

| Sprint | Status |
|---|---|
| Sprint 1 (GEO foundation) | merged 73f6ecb |
| Sprint 1.1 (robots policy AI_ALLOW + AI_BLOCK split) | merged ff2c3f2 |
| Sprint 2 (Lighthouse) | merged 7dfb008 |
| Sprint 2.1 (Worker cache headers, replaces dead _headers) | merged 5840303 |
| Sprint 3 (Reducto eval) | findings only |
| Sprint 4a (integrity + SEO content polish) | merged 21886ca + hotfix 8834068 |
| Sprint 4b (tech debt + ops hardening) | merged fccf9f8 (PR #66 review cycle: nayru/laverna/vaivora/Codex) |
| Sprint 4c (wayback cadence + gitignore + doc consolidation) | direct-to-main: 4099974, f1d76e8; pursue-opsec ff417ef |
| Sprint 6.0 (VLM landscape research) | corrected Infinity-Parser2-Pro: 34B MoE 68GB, not 7B 16GB |
| Sprint 6.1 / 6.1b / 6.1c / 6.1d / 6.1ef | full bake-off complete; ~$3.61 / $30 cap |

### Issues closed during session

- **#61** — Section 6 preserved-pin reaffirmation (false-positive class identified)
- **#63** — c9cc83fcaf43 tranche-detected (stale; promoted 2026-05-15 but issue never closed)
- **#64** — Section 6 false-positive recurrence (now fixed by Sprint 4a A1: `r2_verify_preserved.py` checks `archive_key` not `current_key`)

### Operated VLM answer — LOCKED

**Primary: Sonnet 4.6 single-pass** (cm-CER 20.1%, ~$53/full-corpus, ~15h API single-flight)
**Cross-witness:** GLM-OCR local ($0, 26.9% cm-CER, agreement classification surfaces ~8% LOW-confidence pages for review)
**Cost-shrunk fallback:** gpt-5.4 ($0.17/25pp, 21.3%, 2.5× faster)
**Content-filter backstop:** o4-mini (zero filter trips on FBI content where Opus refused)

**Eliminated (tested, gap-documented):** Reducto, Opus 4.7, Gemini 3.1 Pro, GPT-5.5/5.5-pro, o3 reasoning, all multi-step + adversarial + Sonnet+thinking variants.

**Methodology findings worth keeping:**
- Reasoning architectures hurt HARD-tier OCR across vendors (Sonnet+thinking-16k +4.2pp; o3 +3.3pp) — strong eliminator for future OCR shortlists
- High self-confidence ≠ accuracy on HARD-tier (Gemini 94.2 confidence → 39.6% HARD cm-CER, 2nd-worst in ladder)
- Pre-flight gates discovered: VRAM-fit, billing-tier, content-filter

Canonical bake-off doc: `pursue-opsec-staging/findings/2026-05-18-vlm-bakeoff-final.md` (620 lines; predecessors archived to `findings/archive/`).

## What's Next

### Operator action items — NONE pending

All operator actions from this session are complete:
- ✅ CF Analytics token (build-time env var)
- ✅ Google Cloud Gemini billing
- ✅ OpenAI API key
- ✅ INDEXNOW_KEY + ownership file
- ✅ CF Bot Management list

### Tier-2 registry-signing RFC — DRAFTED (awaiting operator skim)

`pursue-opsec-staging/findings/2026-05-18-tier2-registry-signing-rfc.md` (466 lines, opsec-staging commit `53f8163`, local-only — not pushed pending operator review).

**Recommendation:** Option (c) — Merkle root over canonical-JSON registry rows + operator-signed git tag per promote. Zero per-row friction; reuses operator's existing SSH key (already configured for git push); verification is `git tag -v`, no external service. Estimated implementation effort: ~270 LOC + ~23 tests + one signed tag per promote.

**Three decisions pending operator:**
1. Option lock-in (confirm (c); or layer (b)/(a) on top).
2. Key custody (existing push key vs dedicated signing key, offline-stored).
3. `allowed_signers` location (repo-tracked `docs/allowed-signers.txt` vs out-of-repo declaration).

### Sprint 5 — operator-attention queue (from prior roadmap)

- Display-date phase 4 review (45-75 min operator UI session against `python scripts/curate_dates_ui.py`)
- Black Vault reference corpus replacement (planning + dispatch + review)
- ~~pursue-opsec#1 RFC: tier-2 cryptographic signing of registry rows~~ → drafted this session, awaiting decisions

### Sprint 6.2 — operated VLM pipeline (pending 6 operator decisions)

Per `pursue-opsec-staging/findings/2026-05-18-vlm-bakeoff-final.md` §6:

1. Truth-proxy choice for full-corpus pass (recommend: Haiku-4.5 stay + 5-10 page human-verified calibration sample)
2. Operator review queue tooling for ~8% LOW-class pages (~330 expected)
3. Per-page provenance plumbing (add `engine` field to manifest distinguishing 6 sources)
4. alex-zhang42 corpus retirement (recommend: keep as cold-storage reference, not retire)
5. Budget envelope (~$70 of $90 cap; $86 headroom after $3.61 lifetime bake-off spend)
6. Trigger: attended session required per no-autospend; ~1.5h at 10-way API concurrency; recommend standing up review queue first

### Sprint 7+ — Tier 2 backlog

- `incidents-map-clustering` (`/map`) — net-new geographic browse surface
- `autonomous-finds-pipeline` (private fleet remainder; out of pursue-index repo scope)

## What Was Just Done

**2026-05-17 (later still) — Sprint 4b PR #66 fix-pass applied as one bundled commit on top of `57a8701`. Codex P1 SSR-card-data crawler regression fixed via ItemList JSON-LD; runtime fetch path retained for live grid. nayru P1s (whitespace strip, regex docstring, sitemap recursion test, CardExplorer fetch-fallback test, schema sanity), P2s (literalIdPassages docstring, preserved-false-no-current_key test, countMatchingRows extraction, placeholder removal, PyYAML quirk docstring) all applied. vaivora P2 cache-policy comment fixed; CI minute consolidation deferred to Sprint 4c (real concern but real surgery — needs reliability testing both endpoints). Codex P2 `cache: "force-cache"` → `"default"`. All tests green, arch clean.**

### Sprint 4b PR #66 fix-pass (this session)

**Codex P1 — SSR card data preserved via ItemList JSON-LD.** Sprint 4b Theme F dropped the inline `cards` prop (DOM 695 KB → 26 KB) but CardExplorer's runtime fetch leaves AI crawlers / non-JS engines with an empty grid — regressing the Sprint 1 GEO win. Fix: new `itemListJsonLd()` in `web/src/lib/seo.ts` emits a schema.org ItemList with all 158 cards (card_id + title + canonical URL) injected at SSR time via the existing JsonLd block. Homepage `index.astro` passes the ItemList via the Base.astro `jsonLd` prop. Verified in `dist/index.html`: 158 ListItem entries; total HTML 26 → 53 KB (still 92% smaller than original 695 KB). Crawlers + users both happy.

**Codex P2 — `cache: "force-cache"` → `cache: "default"`.** Extracted `loadCardsSummary` from CardExplorer.tsx to a testable helper at `web/src/components/card-summary-loader.ts`. The new `CARD_SUMMARY_FETCH_OPTIONS = { cache: "default" }` lets the browser honor the Worker's Cache-Control (`worker/index.js::CACHE_POLICY`, 1h fresh + 24h SWR from Sprint 2.1). Previous `force-cache` ignored SWR and pinned stale payloads across tranches.

**nayru P1s addressed (5/5):**
- P1#1 sitemap recursion depth test (`test_expand_sitemap_index_depth_one`): top-level → urlset expanded; nested sitemap-index second-hop dropped. Locks docstring promise.
- P1#2 `resolve_key` whitespace strip: env var value stripped BEFORE truthiness check; falls through to file branch on whitespace-only input; same posture on file branch. 3 new tests.
- P1#3 16-digit numeric regex documented + tested: regex matches pure-digit 16-char strings (hex 0-9 overlap); `literalIdPassages` silently drops unknown IDs so this is benign. Docstring note in `retrieve_literal_id.js`; unit test + end-to-end `retrievePassages` test for the phone-number case.
- P1#4 CardExplorer fetch fallback test: 7 new tests on `loadCardsSummary` covering happy path, URL shape, cache option, network rejection, non-2xx, non-array body. Also added `cards: CardMetadata[] | null` sentinel to suppress the "0 / 0 RECORDS" flash (counter shows "LOADING…" until fetch resolves; `[NO MATCH]` only renders post-resolution).
- P1#5 `build_cards_summary` schema sanity: explicit `Array.isArray(manifest.cards)` check + clear stderr message naming the field + `process.exit(1)`. 2 new tests (not-array, null).

**nayru P2s (apply-all per operator):**
- P2#1 (linear scan over indexPages): NO CHANGE — already documented as deferred in comments.
- P2#2 docstring for `literalIdPassages`: explicit "first chunk per card; multi-page cards rely on semantic tail" + revisit-when criteria.
- P2#3 test for `{preserved: False, no current_key}`: `test_verify_walks_vid_row_with_explicit_preserved_false` locks the OR-semantics of `_latest_preserved_row` so the eligibility branch can't silently regress.
- P2#4 `countMatchingRows` helper extracted in `release.ts`: pure refactor; `countOcrPages` / `countCleanedPages` now both delegate to the shared scaffolding. All 11 existing tests still green.
- P2#5 `indexnow-placeholder.txt` deleted: stub removed from `web/public/`, runbook content moved to `scripts/indexnow_ping.py` module docstring, `.gitignore` adds guard against re-introduction. No public "no key set" page anymore.
- P2#6 PyYAML `True` vs `"on"` quirk: promoted from inline comment in `test_indexnow_workflow.py::test_path_filter_is_narrowed_to_render_affecting_paths` to `_load()` docstring so future readers find it on first look.

**vaivora P2 (1/2):**
- V-P2#1 CardExplorer `_headers` doc nit: updated cache-policy comment to reference `worker/index.js::withCacheHeaders` (the actual policy site post-Sprint-2.1). Lives in both CardExplorer.tsx inline comment and `card-summary-loader.ts` module docstring.
- V-P2#2 doubled CI minute footprint: **DEFERRED to Sprint 4c.** Real concern (indexnow + wayback workflows on identical triggers + 5-min sleeps) but real surgery (need to reliability-test both endpoints under a single dispatcher). Documented as Sprint 4c candidate.

**Style nits:**
- NIT#1 `worker/retrieve.js` re-export comment: rewritten to explain why the surface lives in `retrieve.js` (call-site stability across internal reorganization).
- NIT#4 `card[k] ?? null` shorthand in `build_cards_summary.mjs::slimCard`: applied; semantics unchanged (only `undefined` → `null`, all other values pass through).
- NIT#5 `tests/unit/conftest.py` for repeated `_SCRIPTS` insertion: NOT APPLIED — broader cleanup, defer.

**laverna gap-fill:** clean per prior check. No findings, nothing to fix.

### Test count delta (fix-pass)

- **Python:** 569 → 574 (+5).
- **Web:** 71 → 83 named tests (+12). (Plus 1 unchanged api-page smoke.)
- **Worker:** 135 → 137 (+2).

### arch check

All modified files clean (no errors, only the pre-existing file-size warnings on `scripts/indexnow_ping.py` (342) / `scripts/r2_verify_preserved.py` (232) / `tests/unit/test_indexnow_ping.py` (458) / `tests/unit/test_r2_verify_preserved.py` (427) — all under the error thresholds).

### Files modified

- `web/src/lib/seo.ts` + `seo.test.ts` — new `itemListJsonLd()` builder + 3 tests + banned-words guard updated.
- `web/src/pages/index.astro` — passes `cardItemList` as `jsonLd` prop.
- `web/src/components/CardExplorer.tsx` — `cards` state typed as `CardMetadata[] | null` for the loading sentinel; counter renders "LOADING…" pre-fetch; cache-policy comment updated.
- `web/src/components/card-summary-loader.ts` + `.test.ts` — new module: `loadCardsSummary` extracted from CardExplorer with `cache: "default"` fetch options + 7 tests.
- `web/src/lib/release.ts` — `countMatchingRows` helper extracted; `countOcrPages` / `countCleanedPages` now delegate.
- `web/scripts/build_cards_summary.mjs` + `.test.mjs` — `Array.isArray(manifest.cards)` schema guard + 2 tests; `??` shorthand in slimCard.
- `web/package.json` — `test:lib` script adds the new `card-summary-loader.test.ts`.
- `scripts/indexnow_ping.py` — `resolve_key` whitespace handling; operator runbook docstring (moved from removed placeholder).
- `tests/unit/test_indexnow_ping.py` — 1 sitemap depth test + 3 whitespace-strip tests.
- `tests/unit/test_indexnow_workflow.py` — `_load()` docstring documents PyYAML `True` quirk.
- `tests/unit/test_r2_verify_preserved.py` — 1 preserved-false-no-current_key test.
- `worker/retrieve_literal_id.js` — regex docstring on 16-digit false positive; `literalIdPassages` docstring on first-chunk-per-card.
- `worker/retrieve.js` — re-export comment improved.
- `worker/tests/retrieve_literal_id.test.js` — 1 regex test + 1 end-to-end 16-digit-numeric test.
- `web/public/indexnow-placeholder.txt` — DELETED.
- `.gitignore` — guards against re-introduction of placeholder.

### Operator follow-ups carrying

1. **`INDEXNOW_KEY`** — same as before; operator-action runbook now lives in `scripts/indexnow_ping.py` docstring.
2. **Re-run Lighthouse Best Practices** post-deploy on the homepage.
3. **Sprint 4c candidate:** consolidate indexnow + wayback workflows into a single post-deploy dispatcher (vaivora V-P2#2).

---

**2026-05-17 (later) — Sprint 4b implemented on branch `sprint-4b-polish-and-ops`. Two bundled commits per [[feedback_bundled_commits]]. All tests green; arch warnings only (no errors); no regressions expected on Accessibility 100 / CLS 0 / mobile Performance 90-95 (DOM-size fix should improve, not regress).**

### Theme A — Literal-ID bypass in chat retrieval (worker/)

Sprint 6.0 finding: voyage-3 dense embeddings miss literal-ID lookups ("what's in 13f86e95aed52840?"). Hex strings cluster in the noise floor of natural-language embeddings.

- New `worker/retrieve_literal_id.js` (110 lines): pure helpers (`extractLiteralCardIds`, `literalIdPassages`, `mergeLiteralAndSemantic`). 16-hex regex with `\b` boundaries rejects 15/17-hex.
- `worker/retrieve.js`: prepends exact-match chunks before semantic top-k, dedups by `card_id+page`, caps at k.
- 11 new tests in `worker/tests/retrieve_literal_id.test.js`.

### Theme B — IndexNow ping post-deploy

Bing / Yandex (and ChatGPT-search via Bing) pick up changes within minutes.

- `scripts/indexnow_ping.py` (300 lines, stdlib-only): sitemap → ≤10 000-URL batches → POST to `api.indexnow.org`. Key resolved from `INDEXNOW_KEY` env or `data/indexnow-key.txt` (gitignored). Graceful exit 0 on missing key / per-batch failure.
- `.github/workflows/indexnow-after-deploy.yml`: same narrowed paths + 5-min CFWB-warm sleep + SHA-pinned actions as wayback-after-deploy.
- `web/public/indexnow-placeholder.txt`: operator-action runbook.
- 15 unit tests + 6 workflow tests.

### Theme C — VID integrity in `verify-assets-daily.yml`

28 video registry rows carry `archive_key` + `byte_sha256` but no `current_key` and no `preserved=True`. Pre-Sprint-4b `_latest_preserved_row` silently skipped all 28.

- `scripts/r2_verify_preserved.py`: no-`current_key` rows now treated as implicit preservation rows. Manifest-active rows (current_key set, preserved unset) still skipped — covered by silent-overlay manifest-walk lane; avoid double-hashing.
- Module docstring + `verify-assets-daily.yml` step comment updated.
- 4 new tests pin: VID-walked, VID-mismatch-flagged, mixed-walked, manifest-only-still-skipped.

### Theme D — QC spec stalenesses (AUDIT-ONLY)

Per Sprint 4 brief, two QC scenarios flagged. Audited:
- VID `[NO ASSET URL]` scenario in `card-detail.qc.yaml` — already updated 2026-05-15 (asserts DVIDS embed iframe; inline comment documents the spec drift fix).
- diff scenario 3 cardinality in `diff.qc.yaml` — already updated 2026-05-15 (uses c9cc83fcaf43 vs 4a35f5596951 0/0/122 numbers).

No code changes required; both were spec-drift items resolved in prior commits.

### Theme E — Sprint 1 carry-overs

- **E1 OG number.** `og.png` (canonical) re-rendered against the live manifest (158 / 4,161 / sha c9cc83fcaf43). `og.svg` is a legacy unreferenced file; added deprecation comment.
- **E2 methodology "4,111 of 4,161".** Added `countCleanedPages()` to `lib/release.ts` (reads `/data/pages-cleaned.json`, counts rows with text + no skip_reason). New `RELEASE.cleanedPageCount` drives prose via `formatPageCount()`. Invariant test: `cleanedPageCount > 0 && ≤ ocrPageCount`.
- **E3 `/finds` author.** `author: z.string().optional()` added to finds collection. `articleJsonLd()` already consumed it.
- **E4 Speakable selectors.** methodology / about / cite each went from 1 → 3 selectors. Added matching `id="…"` attributes on second/third paragraphs and key h2s.

### Theme F — CardExplorer 676 KB inline-blob removal

- New `web/scripts/build_cards_summary.mjs` prebuild → `/data/cards-summary.json` (252 KB minified).
- `CardExplorer.tsx`: `cards` prop now optional; absent → fetch on hydration; present → use it (SSR/test).
- `index.astro` drops the `cards` prop.
- 4 new tests.

**Measured impact:** `dist/index.html` 695 203 → 25 915 bytes (-96%). JSON ships separately, CF-edge-cached under Sprint 2.1 `/data/*.json` rule; gzip ~50 KB on the wire. No CLS regression.

### Theme G — Deprecated APIs trace

Audit of `web/src/` + `worker/`: zero internal usage of `unload` / `document.write` / sync XHR / deprecated CSS. Candidates all third-party. Diagnosis written into `docs/perf-baseline.md` with mitigation (CF beacon is token-conditional; can be dropped via env-var if needed).

### Test counts (post-Sprint-4b)

- **Python:** 542 → 565 (+23).
- **Web:** 67 → 72 (+5).
- **Worker:** 124 → 135 (+11).

### arch check

All new/modified files pass. Warnings only (no errors):
- `scripts/indexnow_ping.py` 300 lines.
- `scripts/r2_verify_preserved.py` 232 lines.
- `web/src/components/CardExplorer.tsx` 481 lines (pre-existing >400; +30 this sprint for the optional-cards fetch logic — extraction deferred as single cohesive component).
- `worker/retrieve.js` 329 lines (post-extraction of `retrieve_literal_id.js`).

### Branch state

- Branch: `sprint-4b-polish-and-ops` (off main `8834068`).
- Commit 1 (themes A-C, ops hardening) + Commit 2 (themes E-G, web polish). Theme D audit-only.
- Pending: push + PR + `@codex review` comment.

### Operator-action items (pre-merge / post-deploy)

1. **`INDEXNOW_KEY`** — Generate `secrets.token_hex(16)`, add as repo secret, place matching `<key>.txt` in `web/public/`, delete `indexnow-placeholder.txt`. Until done, workflow exits 0 with "no key found" — no failed runs.
2. **Re-run Lighthouse Best Practices** post-deploy on the homepage. Confirm DOM-size flag is gone and "Uses deprecated APIs" status.

## What's Next

1. **Push `sprint-4b-polish-and-ops` + open PR + request `@codex review`** (matches Sprint 4a posture).
2. **(carrying) Sprint 6.1d Gemini bake-off — operator unblock required.** Project on prepay with $0 balance.
3. **(carrying) Watch Codex re-review on PR #65** (Sprint 4a fix-pass).
4. **(carrying) Wayback first-run validation** post-merge.

---

## Earlier sessions

**2026-05-17 (later) — Sprint 6.1d Gemini bake-off retry (post-billing-connect): still blocked, new diagnosis, eval doc updated in-place.** Operator connected Google Cloud billing on the project tied to `GEMINI_API_KEY` and re-authorized the bake-off. Pre-flight `generate_content` probe (1 token, 4 max output) against five Gemini models (`gemini-3.1-pro-preview`, `gemini-3-pro-preview`, `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-pro-latest`) confirmed billing is now linked — the original free-tier `limit: 0` error is gone — but ALL FIVE 429 with `"Your prepayment credits are depleted"`. Project is on **prepay** billing mode with a $0 balance; all Gemini 3.x and 2.5-pro families share the same project-level prepay pool, so there is no within-Gemini free substitution path. `count_tokens` still succeeds on all five (it doesn't consume credits), confirming SDK/network/key remain valid. The 25-page runner was NOT executed (per the brief's "If still 0, surface the blocker and stop"). $0.00 incremental spend (429s don't bill per Google's docs); $0.00 / $5 cap. Updated `pursue-opsec-staging/findings/2026-05-17-vlm-bakeoff-results.md`: new §3.2a documents the retry + prepay-depleted diagnosis, front-matter has a "retry addendum" entry, §6.7 amended with the post-billing-connect update, §7.6 unblock recipe revised from "enable paid billing" to "top up prepay credits OR switch project to postpay", §8.4 documents the retry posture (no auto-spend, no 25-page runner triggered). Agent-memory `project_gemini_billing_block_6_1d.md` rewritten to reflect the new state. **Operator action required to unblock:** AI Studio → project billing → "Add credits" (a $5 top-up covers expected $0.40-0.80 bake-off spend plus margin), OR switch billing mode from prepay to postpay in the same console. Operated answer (Sonnet 4.6 single-pass) remains unchanged.

**2026-05-17 (evening) — Sprint 4a PR #65 fix-pass: ALL review findings applied as one bundled fix-commit on top of the initial Sprint 4a commit (`52f39c5`). H1-H5 + M1-M3 + M-new + L1-L5 + nayru coverage gaps + nit. Per [[feedback_bundled_commits]], one commit (not five) to keep PR-history tight. Per [[feedback_ship_wired_and_validated]], every fix is test-covered before merge: the Path-collapse bug, the staged-before-diff bug, the if-always commit-back, the rebase-before-push, the origin HEAD wiring, atomic history writes, JSON-decode recovery, max-urls DoS cap, the Base.astro JSON.stringify, the GET docstring drift, the narrowed workflow path filter, the CF Workers Builds docstring, and the CF_MANAGED_BOTS drift-detector all have failing-first tests now green.**

### Fix-pass scope (PR #65)

- **H1 — `scripts/wayback_save.py` --sitemap type fix.** `type=Path` collapsed `https://` to `https:/` because `pathlib.Path` normalizes consecutive slashes. Changed to `type=str`. Integration test `test_collect_urls_accepts_https_sitemap_arg_without_path_collapse` monkey-patches `urlopen` and asserts the URL reaches the http branch intact.
- **H2 — workflow stages history file BEFORE diff.** `git diff --quiet <path>` does NOT detect untracked files — first-run history file would be silently dropped. Now: `git add` then `git diff --cached --quiet`. Tested via `test_commit_step_stages_before_diff_check`.
- **H3 — workflow `if: always()` + script returns 0 on per-URL failure.** Per-URL 429/timeout was failing the workflow and the commit-back step never ran → freshness state was lost. Now: `_run_plan` emits `::warning::` annotations but always succeeds; commit-back runs unconditionally. Tested by `test_run_plan_per_url_failures_return_exit_zero` + `test_run_plan_emits_warning_annotation_for_failures` + `test_commit_step_has_if_always`.
- **H4 — `git pull --rebase origin main` before push.** Mirrors verify-assets-daily.yml race posture for concurrent main writers. Tested by `test_commit_step_rebases_before_push`.
- **H5 — `should_skip_origin_status` wired in.** Was previously dead code. `_filter_dead_origins()` HEADs each URL before submitting to Wayback; `--skip-origin-check` bypasses for "save a known-removed URL before it's also expunged" cases. Two integration tests pin both branches (`test_run_plan_skips_dead_origin_urls`, `test_skip_origin_check_flag_bypasses_head`).
- **M1 — atomic `save_history` (write-temp-then-rename).** `path.with_suffix(...".tmp")` → `tmp.replace(path)` (atomic on POSIX, MoveFileExW on Windows). Tested with `test_save_history_is_atomic_on_partial_write` that monkey-patches `Path.replace` to raise; the original file must be untouched.
- **M2 — `load_history` try/except json.JSONDecodeError.** Corrupt-history file (left by a crashed pre-M1 write, or operator manual edit) now returns `{}` with a `::warning::` annotation rather than crashing the workflow. Tested by `test_load_history_recovers_from_corrupt_json`.
- **M3 — `_expand_sitemap_index` docstring matches behavior.** Old text claimed "recursive" but code expands one level only. Rewrote to explicitly say "follows each child once, does NOT recurse" with a note that nested sub-indexes (we emit none) pass through to Wayback as-is.
- **M-new — `--max-urls` DoS cap (default 1000).** Truncates plan + emits `::warning::` annotation. Prevents a runaway sitemap (typo / attacker-controlled subdomain) from pinning the Wayback queue. Pure helper extracted to `_wayback_helpers.py::apply_max_urls_cap` for testability; three unit tests cover under-cap / at-cap / over-cap behavior plus the end-to-end `test_main_with_args_truncates_oversized_plan`.
- **L1 — `Base.astro` data-cf-beacon JSON.stringify.** Replaced manual template literal with `JSON.stringify({ token: cfAnalyticsToken })`. Astro escapes the HTML output and JSON.stringify handles quotes/backslashes/newlines correctly. Beacon `<script>` remains token-conditional (skipped when env var unset).
- **L2 — GET docstring drift.** Top-level module docstring + `_submit_save` docstring now both say "GET" (matching `method="GET"` in code). Wayback accepts both GET and POST; GET is the conventional save-page-now shape.
- **L3 — workflow path filter narrowed.** Was `web/**` (fired on every state.md sweep, docs/, OG-bot commit). Narrowed to `data/manifests/latest.json` + `web/src/{pages,content,components,layouts}/**`. Tested by `test_path_filter_is_narrowed_to_render_affecting_paths`.
- **L4 — CF Workers Builds dependency documented.** Top-of-file header explains the 5-min sleep is timed against the CFWB dashboard pipeline (auto-deploy on push to main), NOT the in-repo `deploy-cf.yml` (which is workflow_dispatch-only). Note: a CFWB stall means Wayback captures the pre-deploy version — affects snapshot quality, not pipeline correctness. Tested by `test_workflow_documents_cfwb_dependency`.
- **L5 — `scripts/check_cf_managed_bots_drift.py` + `.github/workflows/cf-managed-bots-drift.yml`.** Weekly cron (Mon 09:00 UTC) fetches live `https://pursueindex.com/robots.txt`, extracts the CF-prepended block between `# BEGIN/END Cloudflare Managed` sentinels, diffs against the `CF_MANAGED_BOTS` const in `web/src/lib/robots.ts`. Drift in either direction → `::warning::` annotation → opens a labeled issue (de-duped against any open one). 12 unit tests in `test_check_cf_managed_bots_drift.py` cover the slice extractor, the const-array regex (with inline `//` comment tolerance), case-insensitive diff (CF lowercases `meta-externalagent`), and the end-to-end parse against the real `robots.ts`.

### Nayru coverage gaps (closed)

- **`load_history`/`save_history` round-trip + missing-file + corrupt-JSON cases** — three tests in `test_wayback_save.py`.
- **`_run_plan` mixed 200/429 → exit 0 + history persisted for 200 only** — two tests in `test_wayback_save_integration.py`.
- **main() end-to-end no-URLs, no-plan, oversized-plan cases** — three tests with `urlopen` mocked.
- **`r2_verify_preserved`: row missing `archive_key` → skip + log** — `test_verify_skips_row_missing_archive_key` written first, fails on `KeyError`, fixed by `row.get("archive_key")` + skip branch. The branch made `verify_preserved` 56 lines (over the 50-line limit), so the per-row logic was extracted to `_check_one_row()` returning `(status, mismatch_entry_or_none)`. Both functions now under limit.
- **robots.ts: AI_ALLOW survives the CF_MANAGED_BOTS filter** — `test_AI_ALLOW_survives_the_CF_MANAGED_BOTS_filter` pins that if CF later adds (e.g.) `Applebot` to its Managed block, our explicit `Allow: /` still renders because the filter applies to AI_BLOCK only.

### Nits

- `test_r2_verify_preserved.py:97` docstring fixed: `current_key` → `archive_key`.

### Refactor for arch compliance

- Extracted pure helpers from `wayback_save.py` to `scripts/_wayback_helpers.py` (~106 lines): `parse_sitemap_urls`, `is_fresh`, `build_save_url`, `build_plan`, `should_skip_origin_status`, `apply_max_urls_cap`. `wayback_save.py` re-imports them so the public-test surface is unchanged. Without this split the main file would have crossed the 400-line error threshold once the new --max-urls + origin-HEAD + JSON-recover paths landed.

### Test counts (post-fix)

- **Python:** 542 passed (+35 from 507 baseline: +5 in test_wayback_save, +8 in new test_wayback_save_integration, +7 in new test_wayback_workflow, +12 in new test_check_cf_managed_bots_drift, +1 in test_r2_verify_preserved). 0 fail.
- **Web (lib):** 57 (+1 from 56 baseline: AI_ALLOW-survives-CF-managed-filter). 0 fail. test:llms unchanged 9; test:api-page unchanged 1.
- **Worker:** 124 (unchanged). 0 fail.
- **Astro build:** 182 pages built in ~6.5s; `dist/robots.txt` still clean (no duplicates with CF Managed).

### arch check

Clean (or warning-level only) on every modified/new file:
- `scripts/wayback_save.py` — 366 lines (warning, well under 400 error)
- `scripts/_wayback_helpers.py` — clean (106 lines)
- `scripts/check_cf_managed_bots_drift.py` — clean (186 lines)
- `scripts/r2_verify_preserved.py` — 204 lines (warning, just over 200)
- `web/src/layouts/Base.astro` — clean
- `web/src/lib/robots.test.ts` — clean
- `tests/unit/test_wayback_save.py` (289 lines, 20 funcs) — clean
- `tests/unit/test_wayback_save_integration.py` (379 lines, 8 funcs) — clean
- `tests/unit/test_wayback_workflow.py` — clean
- `tests/unit/test_check_cf_managed_bots_drift.py` — clean
- `tests/unit/test_r2_verify_preserved.py` — clean

### Branch state

- Branch: `sprint-4a-integrity-seo` (rev: fix-pass commit on top of `52f39c5`).
- **Pushed** to origin after this commit so Codex re-reviews PR #65 within ~5 min.

### Operator-action items (unchanged from prior Sprint 4a entry)

1. **`PUBLIC_CF_ANALYTICS_TOKEN` env var.** Set in CF Pages → Settings → Environment variables before deploy. Beacon script is skipped at build time without it.
2. **Wayback workflow first-run.** First production run will save ~180 sitemap URLs at 2s/URL ≈ 6 min wall-clock. Now with `--skip-origin-check` available if the operator ever wants to bypass the HEAD probe.
3. **Verify Lighthouse SEO clears.** After deploy, run Lighthouse SEO audit on `/`.
4. **(new) `cf-managed-bots-drift` workflow.** Files an issue automatically on Mon 09:00 UTC if CF expands the Managed list upstream. Watch for the `cf-managed-drift` label.

## What's Next

1. **(new) Sprint 6.1d Gemini bake-off — operator unblock required.** Project on prepay with $0 balance. AI Studio → project billing → "Add credits" ($5 covers expected $0.40-0.80 spend with margin), OR switch billing mode to postpay. Once unblocked, single command executes the bake-off: `cd pursue-opsec-staging/scratch/vlm-bakeoff-2026-05-17 && ./.venv-bakeoff/bin/python run_gemini_bakeoff.py && ./.venv-bakeoff/bin/python score_locals.py && ./.venv-bakeoff/bin/python score_by_difficulty.py`. Eval-doc update points are pre-staked at §3.2a / §4.1 (gemini_3_1_pro_preview row) / §6.7 (one of three outcome paths) / §7.6 / §9.6. No further code or doc work needed until operator confirms top-up.
2. **Watch Codex re-review on PR #65.** If clean, merge to main and let the CF Workers Builds pipeline auto-deploy. Then set `PUBLIC_CF_ANALYTICS_TOKEN`.
3. **Wayback first-run validation** (unchanged from prior entry).
4. **Sprint 4b carry-forward candidates** (unchanged): IndexNow ping post-deploy, literal-ID bypass in `worker/`, QC spec staleness, Sprint 1 carried follow-ups.

---

**2026-05-17 — Sprint 4a (integrity layer + SEO polish) implemented on branch `sprint-4a-integrity-seo`. Single uncommitted change-set bundling Theme A (provenance/integrity hardening) and Theme B (homepage SEO surface polish); tests + arch checks clean; build green; not yet pushed pending operator review.**

### Theme A — Provenance & integrity

- **A1: `scripts/r2_verify_preserved.py` reads `archive_key`, not `current_key`.** After the 2026-05-14 Section 6 preserved-pin reaffirmation policy (`13f86e95aed52840`), `current_key` legitimately serves NEW upstream bytes while OLD preserved bytes live at `archive/<sha>.<ext>`. Reading current_key was producing daily false-positive `preserved-tampered` issues (Issues #61, #64 closed; cron kept re-filing). The verify now reads the immutable archive copy directly — which is what "preservation" structurally means. Module docstring rewritten to reflect the new behavior; mismatch report renames `current_key` → `archive_key` for operator clarity. Three new unit tests cover the Section-6 reaffirmation case + the archive-key read assertion + the renamed report field. `tests/unit/test_r2_verify_preserved.py` 5 → 8 cases, all green.
- **A2: Wayback wiring built fresh.** Re-searched pursue-index, pursue-opsec-staging, worker, and `.github/` for any existing wayback / web.archive / save endpoint references — only the existing `archive.org_bot` AI_ALLOW entry in `robots.ts` came up. No prior script. Built `scripts/wayback_save.py` (pure-stdlib, strict-sequential with 2s delay, 24h freshness gate against `data/wayback-history.json`, sitemap-xml or `--url` input, idempotent). Added `.github/workflows/wayback-after-deploy.yml` — fires on push to main scoped to changes in `data/manifests/latest.json` OR `web/**`, plus `workflow_dispatch`. Waits 5 min for CF edge warm before submitting. Commits history JSON back to the repo so subsequent runs honor the freshness window. 13 new unit tests cover the parser, freshness gating, plan filtering, save-URL construction, and origin-status gating. `tests/unit/test_wayback_save.py` new file, all 13 green.

### Theme B — SEO content polish

- **B1: Title tags 41 → 50-60 chars.** Homepage: `PURSUE://INDEX — Declassified DOW UAP / UFO Document Archive` (60 chars). Methodology: `METHODOLOGY — PURSUE://INDEX — DOW UAP / UFO OCR Pipeline` (57). About: `ABOUT — PURSUE://INDEX — Declassified DOW UAP / UFO Archive` (59). Cite: `Citation Guide — PURSUE://INDEX — Declassified DOW UAP Archive` (62). All add `Declassified` + `UFO` (consumer-search keyword) on top of the existing brand line.
- **B2: Meta descriptions 88 → 120-160 chars.** Homepage: `Search 4,161 OCR'd pages of the declassified U.S. Department of War PURSUE UAP / UFO release — FBI memos, NASA records, mission reports & AARO findings.` (152 chars, page count templated via `formatPageCount(RELEASE.ocrPageCount)`). Methodology 149. About 158. Cite 150. Each adds the keyword cluster (declassified, FBI, NASA, AARO, mission reports) without keyword-stuffing.
- **B3: Keyword distribution.** New title + meta cover the must-haves (UAP, declassified, Department of War, OCR'd pages) and strong-adds (military / mission report via "mission reports", AARO, FBI, NASA) and the edge-add (UFO). Homepage H1 already keyword-bearing (`DEPARTMENT OF WAR / PURSUE` + UAP subtitle); no H2 addition needed. seo.test.ts banned-words guard (`best`, `leading`, `ultimate`, `revolutionary`…) reviewed against new copy — clean.
- **B4: robots.txt CF-managed duplicate trim.** Added `CF_MANAGED_BOTS` const (9 entries: Amazonbot, Applebot-Extended, Bytespider, CCBot, ClaudeBot, CloudflareBrowserRenderingCrawler, Google-Extended, GPTBot, meta-externalagent). `buildRobotsTxt()` filters AI_BLOCK against this list at render time; AI_BLOCK itself unchanged so the source-of-truth policy still lists every bot we want blocked, regardless of which layer enforces it. Wildcard `User-agent: *` block + `Disallow: /api/` removed (CF Managed renders the canonical wildcard with Content-Signal directives). Rendered `dist/robots.txt`: 10 non-CF-managed Disallow blocks (PanguBot, TikTok Spider, FacebookBot, Diffbot, ImagesiftBot, img2dataset, cohere-training-data-crawler, Terracotta Bot, Timpibot, Novellum AI Crawl) + 22 Allow blocks + Sitemap + Host. **No duplicate User-agent lines with CF's prepended block.** 4 new robots tests assert the dedupe (CF_MANAGED_BOTS membership + rendered-body absence + non-CF-managed presence + wildcard removal); 11 existing tests updated to the new contract. `robots.test.ts` 15 → 19 cases, all green.
- **B5: Cloudflare Web Analytics beacon wired in `Base.astro`.** Workers Static Assets bypasses CF Pages' HTML-rewriter beacon injection — SEOPTIMER detected "Cloudflare Browser Insights" via tech fingerprint but view-source showed no script tag, confirming the gap. Added token-conditional `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "..."}'>` reading from `PUBLIC_CF_ANALYTICS_TOKEN` (Astro env var). CSP already allows `static.cloudflareinsights.com` (script-src) + `cloudflareinsights.com` (connect-src) per `worker/index.js`. **Path (a)** taken — beacon code shipped, token-conditional render means local-dev preview builds without the env var skip the script entirely (no broken token interpolation). **Operator action required: set `PUBLIC_CF_ANALYTICS_TOKEN` in CF Pages → Settings → Environment variables before deploy.** Token sourced from CF dashboard → Analytics & Logs → Web Analytics → site token.
- **B6: `docs/perf-baseline.md` post-Sprint-2.1 baseline section filled.** All six regions captured: US West 95, US East 92, Germany 90, Finland 93, Japan 90, Australia 93. Resource size 8.26 MB → 826 KB (-89%). Requests 18 → 11. CLS 0.03 → 0 (beaten). All six Sprint 2 targets MET or BEATEN — APAC catastrophe fully resolved (Japan +53, Australia +56, Finland +49). Sprint 2 + 2.1 commit references documented in the new section.

### Test results

- **Web (lib/test:lib + test:llms + test:api-page):** 56 lib (+4 from Sprint 4a: 19 robots up from 15, plus unchanged release 10 + seo 18 + homepage-search 9) + 9 llms + 1 api-page = 66 in `npm run test`. All green.
- **Python (`pytest tests/`):** 507 passed (+16 from Sprint 4a: 3 new in test_r2_verify_preserved + 13 new in test_wayback_save; baseline 491). 0 fail.
- **Worker:** 124 passed (unchanged from Sprint 2.1). 0 fail.
- **Astro build:** 182 pages built in 6.7s. `dist/robots.txt` shows the clean filtered output; `dist/llms.txt`, `dist/llms-full.txt`, `dist/sitemap-index.xml` all emitted.

### arch check

Clean on every modified/new source file:
- `scripts/r2_verify_preserved.py` — clean
- `scripts/wayback_save.py` — 1 warning (file too large, 302 > 200 warning threshold; well under 400 error threshold)
- `tests/unit/test_r2_verify_preserved.py` — clean
- `tests/unit/test_wayback_save.py` — clean
- `web/src/lib/robots.ts` — clean
- `web/src/lib/robots.test.ts` — clean
- `web/src/pages/{index,methodology,about,cite}.astro` — clean
- `web/src/layouts/Base.astro` — clean

### Branch state

- Branch: `sprint-4a-integrity-seo` (created from `main` post-Sprint-2.1).
- Single uncommitted change-set. Bundled per [[feedback_bundled_commits]].
- **NOT pushed.** Operator reviews locally first.

### Operator-action items (deferred to operator)

1. **`PUBLIC_CF_ANALYTICS_TOKEN` env var.** Set in CF Pages → Settings → Environment variables (sourced from CF dashboard → Analytics & Logs → Web Analytics → site token). Until set, the beacon `<script>` is skipped at build time — code-side change is harmless without the token.
2. **Wayback workflow first-run.** First production run will save ~180 sitemap URLs at 2s/URL ≈ 6 min wall-clock. The committed `data/wayback-history.json` is empty at branch-tip; first run populates it. Subsequent runs only re-save URLs whose 24h freshness expired.
3. **Verify Lighthouse SEO clears.** After deploy, run Lighthouse SEO audit on `/` — the prior "robots.txt is not valid" + duplicate User-agent warnings should be gone. Title/meta description length warnings should also clear.

## What's Next

1. **Operator review + push.** Branch `sprint-4a-integrity-seo` is local-only. Review the rendered `dist/robots.txt` sample above, confirm the title/meta lengths match the brief (60 / 152 / 149 / 158 / 150), then `git push -u origin sprint-4a-integrity-seo` and merge. Then set `PUBLIC_CF_ANALYTICS_TOKEN` per operator-action #1 above.
2. **Wayback first-run validation.** After merge, the workflow fires on the next `data/manifests/latest.json` change (next tranche poll) OR can be triggered manually via `workflow_dispatch`. Watch the run log; if Wayback rate-limits surface as 429s, increase `--delay-seconds` from 2 to 3+ in the workflow yaml.
3. **Sprint 4b carry-forward candidates surfaced during Sprint 4a:**
   - IndexNow ping post-deploy (Sprint 4 brief item, not bundled here).
   - Literal-ID bypass in `worker/` chat retrieval (Sprint 4 brief item).
   - QC spec staleness — 2 cases per Sprint 4 brief (VID `[NO ASSET URL]`, diff scenario 3 cardinality).
   - Sprint 1 carried follow-ups still open: OG SVG hardcoded `4,161`, methodology `4,111` (template or leave as prose), /finds author schema field, Speakable selector expansion.

---

**2026-05-17 (afternoon, cross-repo) — VLM bake-off Sprint 6.1b: local-candidate completion. GLM-OCR ran on the 25-page golden set; capped-mean CER 26.9% vs Sonnet 4.6's 20.1%. Sonnet 4.6 confirmed as the operated answer for the upcoming pursue-index vision-augment pass (miss exceeds the >5 pp Sonnet-confirm criterion). Two candidates still recoverable: dots.mocr blocked on flash-attn install authorization; Infinity-Parser2-Pro skipped on VRAM fit (~34 B-param MoE, ~68 GB bf16 footprint vs RTX 5090's 32 GB). Full results: `pursue-opsec-staging/findings/2026-05-17-vlm-bakeoff-results.md`. Scratch scripts + per-engine results JSON: `pursue-opsec-staging/scratch/vlm-bakeoff-2026-05-17/`. Zero impact on pursue-index source tree — bake-off ran in a dedicated venv (`pursue-opsec-staging/scratch/vlm-bakeoff-2026-05-17/.venv-bakeoff/`) so the pursue-index venv's `transformers==4.57.6` pin is untouched.**

---

**2026-05-17 — Sprint 1.1 (robots.txt allow/block policy split) implemented on branch `sprint-1.1-robots-policy`. Single uncommitted change-set; aligns the generated `/robots.txt` with the operator's stated policy — surface our content (search/user/archivers), block training-corpus crawlers. Resolves the visible contradiction between the prior single allow-list and CF's Managed robots.txt Disallow override.**

### Source-of-truth split (`web/src/lib/robots.ts`)

- Replaced single `AI_CRAWLERS` (27 entries, all Allow) with two typed lists:
  - **`AI_ALLOW` (22 entries)** — bots that surface our content to user-driven sessions OR archivers (preservation): `ChatGPT-User`, `OAI-SearchBot`, `Claude-User`, `Claude-SearchBot`, `Googlebot`, `Bingbot`, `Applebot`, `PerplexityBot`, `Perplexity-User`, `DuckAssistBot`, `MistralAI-User`, `Meta-ExternalFetcher`, `PetalBot`, `Amzn-SearchBot`, `Amzn-User`, `Google-CloudVertexBot`, `ProRataInc`, `Cloudflare Crawler`, `Anchor Browser`, `Manus Bot`, `archive.org_bot`, `Arquivo Web Crawler`.
  - **`AI_BLOCK` (18 entries)** — bots whose stated purpose is bulk corpus ingestion for LLM pretraining: `GPTBot`, `ClaudeBot`, `Google-Extended`, `Applebot-Extended`, `PanguBot`, `Bytespider`, `TikTok Spider`, `CCBot`, `Meta-ExternalAgent`, `FacebookBot`, `Amazonbot`, `Diffbot`, `ImagesiftBot`, `img2dataset`, `cohere-training-data-crawler`, `Terracotta Bot`, `Timpibot`, `Novellum AI Crawl`.
- `buildRobotsTxt()` emits the Disallow section **before** the Allow section so first-match parsers (RFC 9309) honor the deny rule before any other.
- Wildcard `User-agent: *` block + `/api/` Disallow + Sitemap/Host directives preserved.
- Operator-specific decisions encoded: Amazon granular (general Amazonbot blocked, search/user variants allowed); Terracotta + Timpibot flipped to Block; Novellum blocked conservatively; Cloudflare Crawler and Google Vertex Allow.

### Test rewrite (`web/src/lib/robots.test.ts`)

- 15 node:test cases (up from 7). Coverage includes:
  - Full list-membership snapshots for both `AI_ALLOW` and `AI_BLOCK`.
  - Mutual-exclusion guard (Terracotta-style overlap regression test).
  - Per-list dedupe guard.
  - Critical-bot spot checks (ClaudeBot/GPTBot/Google-Extended/etc. must be Block; ChatGPT-User/Googlebot/Bingbot etc. must be Allow).
  - Paired-vendor table test — confirms each `Allow`/`Disallow` pairing for the 14 vendor pairs.
  - Order assertion — `AI_BLOCK` section precedes `AI_ALLOW` in the rendered body.
  - Cardinality: total `Allow: /` = `AI_ALLOW.length + 1` (wildcard); total `Disallow: /` = `AI_BLOCK.length`; `Disallow: /api/` appears exactly once.

### Verification

- `npm run test` — all green: 52 lib tests + 9 llms + 1 api-page; +8 net tests from Sprint 1.1.
- Worker: `node --test tests/*.test.js` — 108 passed, 0 fail.
- Python: `pytest tests/ -q` — 491 passed.
- `bpsai-pair arch check` — clean on `web/src/lib/robots.ts` (197 lines), `web/src/lib/robots.test.ts` (337 lines), `web/src/pages/robots.txt.ts` (unchanged).

**2026-05-17 — Sprint 2.1 (cache-headers Worker fix) merged to main as `5840303`.** Workers Static Assets with `run_worker_first: true` doesn't honor `_headers`; cache directives now live in `worker/index.js::CACHE_POLICY` applied by `withCacheHeaders()`. `web/public/_headers` deleted. 124 worker tests (+16 cache cases), arch check clean. Path-based TTL: `/_astro/*` immutable 1yr; `/data/<file>.json` + `/data/embeddings.bin` 1h fresh + 24h SWR; `/data/thumbs/*` + `/og/*` 1wk + 30d SWR; `/llms*.txt` + `robots.txt` + `sitemap*.xml` 1h fresh. Operator follow-up: `curl -sSI https://pursueindex.com/_astro/<any>.css | grep cache-control` should show `max-age=31536000, immutable`; re-run PSI from six baseline regions ~5 min after CF edge warm.

## What's Next

1. **Operator review + push.** Branch `sprint-1.1-robots-policy` is local-only. Review the rendered robots.txt sample (15 Disallow blocks then 22 Allow blocks then wildcard), confirm bot lists match policy, then `git push -u origin sprint-1.1-robots-policy` and merge.
2. **Sprint 1.1.b (operator-side, NOT code).** Mirror the AI_BLOCK list in Cloudflare Bot Management (or WAF custom rules). robots.txt is voluntary — the dashboard rule is what actually stops a non-compliant crawler. Concrete steps:
   - CF dashboard → Security → Bots → Bot Management → add each `AI_BLOCK` UA to the "block" managed list, OR
   - WAF → Custom Rules → "block if `cf.bot_management.verified_bot == false AND http.user_agent contains <name>`" per Block entry.
3. **Resume Sprint 2.1 (cache-headers).** That branch (`sprint-2.1-cache-headers`) is separately in-flight with its own changes (`worker/index.js`, `cache_headers.test.js`, `web/public/_headers` reorg). Independent of Sprint 1.1.
4. **Cross-repo: Sprint 6.2 vision-augment pipeline plumbing.** With Sonnet 4.6 confirmed as the operated VLM (bake-off 6.1b), the next backend work item is wiring it into `pursue-index/src/pursue_index/ocr/` as a third engine alongside Surya + Haiku auto-mode. Two operator decisions feed into that plan: (a) auto-mode threshold recalibration (the existing `70` confidence cut tuned for Haiku is too aggressive for Sonnet's wider confidence range — Sonnet self-rates 30 on hand-sketched-diagram pages even when substantively correct); (b) per-page provenance plumbing — manifest needs to distinguish Surya-from-original vs Sonnet-from-original vs operator-attested-corrected. Findings doc: `pursue-opsec-staging/findings/2026-05-17-vlm-bakeoff-results.md` §6.2 + §7.
5. **Cross-repo: Sprint 6.1c (optional, recoverable).** Two local OCR candidates still uncompleted from the bake-off. Operator chooses which to unblock: (a) authorize `flash-attn` install in the bake-off venv (small, fast, unblocks dots.mocr — ~6 GB VRAM expected, MIT); (b) download Infinity-Parser2-Flash (the smaller variant of Infinity-Parser2 — the Pro is a 34B-MoE, fails VRAM fit on the 5090); (c) skip both and lock in Sonnet 4.6 as final. Path (c) is the default if not opened in the next session.

---

**2026-05-16 — Sprint 2 (Lighthouse perf-pass) implemented on branch `sprint-2-lighthouse`. Single uncommitted change-set targeting the homepage's TBT + LCP + resource-size catastrophe. Tests + arch checks clean; build green; not yet pushed pending operator review.**

### Diagnosis (`docs/perf-baseline.md` — new file, "Sprint 2 diagnostic" section)

Three root causes of the 37-mobile-score in APAC + the universal 5.6–9s TBT, identified by inspecting `web/dist/` after the local build:

1. **`<SearchIsland client:load>` on `/` hydrates eagerly** and fetches `/data/pages.json` (7.1 MB unminified) on every homepage visit. The fetch itself is the LCP-path asset — APAC + Finland regions have no warm CF edge cache for it, hence the 13.1s LCP. The subsequent synchronous MiniSearch index build over 4,127 docs is the dominant TBT contributor.
2. **`<CardExplorer client:load>` on `/` inlines the full 158-card manifest** as serialized island props. dist/index.html is **676 KB unminified / 67 KB gzipped**. Hydrates eagerly + fetches `/data/novelty.json` (44 KB) on mount.
3. **No `web/public/_headers`** — `/data/*` assets serve with the CF assets binding's default cache headers, which don't fill regional edges aggressively.

### Phase 2 — TBT quick wins

- **`web/src/components/HomepageSearch.tsx` (new)** — tiny Preact form that submits to `/search?q=<query>`. Does NOT load MiniSearch, does NOT fetch pages.json. Mirrors the prior hero look (input + example chips + kbd hint).
- **`web/src/components/homepage-search.ts` (new)** — pure `buildSearchHref()` helper for URL construction. Encoded properly via `encodeURIComponent` (spaces → `%20`, not `+`; reserved chars escape).
- **`web/src/components/homepage-search.test.ts` (new)** — 9 node:test cases: empty/whitespace query, ASCII/Unicode/reserved-char encoding, base normalization (trailing slash, nested preview paths). All 9 green.
- **`web/src/pages/index.astro`** — swaps `<SearchIsland client:load>` → `<HomepageSearch client:idle>` and `<CardExplorer client:load>` → `<CardExplorer client:visible>`. No layout-shift risk: hero is server-rendered + CardExplorer renders below the fold with intrinsic grid sizing.

### Phase 3 — LCP regional fix

- **`web/public/_headers` (new)** — explicit Cloudflare cache directives:
  - `/_astro/*` → `public, max-age=31536000, immutable` (hashed filenames, safe to cache forever)
  - `/data/*` → `public, max-age=3600, stale-while-revalidate=86400` (1h fresh, 24h SWR)
  - `/data/thumbs/*`, `/data/video-posters/*`, `/og/*` → `public, max-age=604800, stale-while-revalidate=2592000`
  - `/og.png`, `/og.svg`, `/favicon.*` → `public, max-age=604800`
  - `/llms.txt`, `/llms-full.txt` → `public, max-age=3600`

### Phase 4 — Resource size

- **`web/astro.config.mjs`** — adds `vite.build.target: "es2022"`. Bumps Vite's transpile target from ES2017 → ES2022; lets MiniSearch / Preact / regl-scatterplot ship without re-downleveling their already-modern bundles.

### Phase 5 — Polish

- No webfonts in use (`global.css` is system stack only — `ui-monospace`/`system-ui`). `font-display: swap` n/a; no `<link rel="preconnect">` needed.
- No third-party origins on `/` requiring preconnect. Anthropic-API origin is `/chat`-route only; Voyage embeddings are Worker-side only.

### Measured locally (post-build)

| Asset | Before | After | Delta |
|---|---|---|---|
| `dist/index.html` gzipped | ~67 KB | **63 KB** | -4 KB |
| Homepage-island eager JS | SearchIsland 12K + search-result-highlight 18K + CardExplorer 9.8K = **39.8K** raw | **HomepageSearch 1.8K** (rest deferred) | -38K on first paint |
| `pages.json` requested on `/` | 7.1 MB | **0** | -7.1 MB |
| `novelty.json` requested on `/` | 44 KB | 0 (deferred to `client:visible`) | -44 KB on first paint |
| `_headers` directives | absent | 9 path rules | n/a |

### Test results

- **Web:** 190 tests green (35 lib + 9 llms + 145 component + 1 api-page snapshot — added 9 homepage-search tests this pass).
- **Python:** 491 passed.
- **Worker:** 108 passed.
- **Astro build:** 182 pages built in 6.4s. `dist/llms.txt`, `dist/llms-full.txt`, `dist/robots.txt`, `dist/_headers` all emitted.

### arch check

Clean on each of the 5 modified/new files.

### Branch state

- Branch: `sprint-2-lighthouse` (created from `main` at `73f6ecb`).
- Single uncommitted change-set. Bundled per [[feedback_bundled_commits]].
- **NOT pushed.** Operator reviews locally first.

### Verification plan (cannot fully verify locally)

Lighthouse regional scores require a real CF Pages deploy → PSI run from each region. Once operator approves + pushes:

1. CF Pages preview deploy completes.
2. `npx lighthouse https://<preview-url> --preset=mobile` for a local sanity check (no regional data).
3. After merge + prod deploy, wait ~5 min for CF edge warming, then re-run PageSpeed Insights across the six baseline regions (US West, US East, Germany, Finland, Japan, Australia).
4. Post-fix row in `docs/perf-baseline.md` gets the actual numbers; if any metric misses target, file a Sprint-4 follow-up.

### Operator-action items (deferred to operator)

1. CF Pages dashboard — confirm "auto minify HTML" is OFF (Astro already minifies).
2. CF Pages dashboard — verify "Tiered Cache" is ON for the `pursueindex.com` zone (materially helps APAC).
3. After deploy + cache warm, re-run PSI from the six regions and fill the post-fix row.

## What Was Just Done

**2026-05-16 — Sprint 1 (GEO foundation) implemented on branch `sprint-1-geo-foundation`. Four work items shipped in a single uncommitted change-set; tests + arch checks clean; build green; not yet pushed pending operator review.**

Four items, all four green:

### Item 1: llms.txt + llms-full.txt build pipeline

- `web/scripts/build_llms_txt.mjs` — Node ESM prebuild script (no new deps). Walks `data/manifests/latest.json` for cards, `web/public/data/pages.json` for OCR text, `web/src/content/finds/**` for finds entries. Emits two artifacts:
  - `web/public/llms.txt` (~29 KB) — Jeremy Howard convention index. Meta + Cards + Finds sections, one canonical URL per entry.
  - `web/public/llms-full.txt` (~450 KB) — anchor-stable H2 corpus: `## Project overview`, `## Methodology`, `## About`, `## How to cite`, `## Cards`, `## Finds`. Cards get H3 + agency/date/URL/war.gov-source + 500-char OCR page-1 excerpt. Finds get H3 + canonical URL + frontmatter summary + body with `<Cite>` stripped to plain bracket markers.
- Wired as `npm run prebuild` so `astro build` triggers it automatically; verified `web/dist/llms.txt` and `web/dist/llms-full.txt` are emitted on build.
- `web/scripts/build_llms_txt.test.mjs` — 9 smoke tests on the in-process renderers (anchor-stable H2 set, per-card H3 + URLs, 500-char excerpt truncation, frontmatter parser, MDX `<Cite>` stripping).

### Item 2: AI-crawler robots.txt allowlist

- `web/src/lib/robots.ts` — content builder (27 named AI-crawler user-agents in `AI_CRAWLERS` const, exported for audit). Alphabetical-by-vendor: Amazon, Anthropic (anthropic-ai / Claude-Web / ClaudeBot / ClaudeBot-User), Apple (Applebot / Applebot-Extended), ByteDance (Bytespider), Common Crawl (CCBot), Cohere (cohere-ai), Diffbot, DuckDuckGo (DuckAssistBot), Google (Google-Extended / GoogleOther), Meta (FacebookBot / Meta-ExternalAgent / Meta-ExternalFetcher), Mistral (Mistral-AI), OpenAI (ChatGPT-User / GPTBot / OAI-SearchBot), Perplexity (Perplexity-User / PerplexityBot), Petal (PetalBot), xAI (Grok / xAI), You.com (YouBot).
- `web/src/pages/robots.txt.ts` — dynamic Astro endpoint serving the generated body with `Cache-Control: public, max-age=3600`.
- `web/public/robots.txt` — deleted (replaced by the dynamic endpoint).
- `web/src/lib/robots.test.ts` — 7 tests verifying every named crawler has an explicit `Allow: /` block, the wildcard fallback + `Disallow: /api/` is preserved, and `Sitemap:` + `Host:` directives are present. Fixes the Lighthouse "robots.txt is not valid" SEO audit finding.

### Item 3: JSON-LD coverage

- `web/src/lib/seo.ts` — typed builders for `organizationJsonLd()`, `websiteJsonLd()` (with SearchAction), `datasetJsonLd()` (dual licensing: Apache-2.0 code + usa.gov public-domain, Dataset distribution endpoints), `digitalDocumentJsonLd()` (with war.gov `sameAs`, GovernmentOrganization creator, OCR text slice truncated at 5KB), `articleJsonLd()` (with citation array linking primary card URLs), `breadcrumbJsonLd()`, `speakableJsonLd()`.
- `web/src/lib/seo.test.ts` — 18 tests, including a banned-words guard (`best`, `leading`, `ultimate`, `revolutionary`…) running over every builder's output so any future drift into promotional language fails loudly.
- `web/src/components/JsonLd.astro` — single-purpose injector. Accepts object or array; one `<script type="application/ld+json">` per entry (Google + AI-Overviews prefer separate tags over `@graph`). Defensive `</script>` sentinel escape for future-proofing.
- Integration:
  - **Root layout** (`Base.astro`): Organization + WebSite + Dataset auto-injected on every page via `RELEASE` constants from `web/src/lib/release.ts`.
  - **Card pages** (`card/[card_id].astro`): DigitalDocument with first-page OCR text (loaded once per build via `fs.readFileSync` of pages.json — explicitly avoided ES-importing the 7MB file) + BreadcrumbList.
  - **/finds entries** (`finds/[slug].astro`): Article + BreadcrumbList. Article.citation populated from frontmatter `cards` field.
  - **/methodology, /about, /cite**: Article + Speakable + BreadcrumbList. Added `id="methodology-lede"` / `id="about-lede"` / `id="cite-lede"` to the lead paragraphs so the Speakable CSS selectors resolve.

### Item 4: `web/src/lib/release.ts` consolidation

- `web/src/lib/release.ts` — typed `RELEASE` const reading `web/src/data/manifest.json` (card count, csv_sha256, fetched_at) + `data/manifests/snapshots/index.json` (tranche count) + `web/public/data/pages.json` via fs (OCR page count, with `4161` fallback if file missing). Exports `currentTrancheId`, `currentTrancheIdShort` (12-char), `cardCount`, `ocrPageCount`, `lastTrancheDate`, `release01Date` (frozen `2026-05-08`), `trancheCount`, `fetchedAtIso`, plus `formatCardCount()` / `formatPageCount()` thousands-separator helpers.
- `web/src/lib/release.test.ts` — 10 schema/shape tests asserting the public contract.
- Replaced hardcoded `4,161` in `web/src/pages/index.astro` (meta description + hero PAGES strip) and `web/src/pages/methodology.astro` (3 locations) with `formatPageCount(RELEASE.ocrPageCount)`. Conservative — only numeric tokens; prose left intact.
- Used JSON import attributes (`with { type: "json" }`) so the file works under both Astro (vite) and `node --test` (Node 24+).

### Test results

- **Web (this PR's scope):** 35 lib tests (release + seo + robots) + 9 llms tests + 145 existing component tests + 1 api-page snapshot = 190 green, 0 fail.
- **Python:** 491 passed (no regressions).
- **Worker:** 108 passed (no regressions).
- **Astro build:** 182 pages built in 17.4s. `dist/llms.txt`, `dist/llms-full.txt`, `dist/robots.txt` all emitted. View-source on `/`, `/card/<any>`, `/finds/<any>` shows the expected JSON-LD scripts.

### arch check

Clean on every new/modified file (17 files checked individually).

### Branch state

- Branch: `sprint-1-geo-foundation` (created from `main` at `3236a18`).
- Single commit on the branch. Bundled per [[feedback_bundled_commits]] — operator prefers fewer larger commits over churn-style splits, and these four items ship as one PR per the brief.
- **NOT pushed.** Operator reviews locally first.

### Operator follow-ups / unresolved

1. **OG SVG (`web/public/og.svg` line 61)** still hardcodes `4,161` because it's an asset file, not a source file. Re-rendering the OG card with the dynamic number requires running the existing OG-build pipeline (`scripts/build_finds_og_images.py` and friends); intentionally out of Sprint-1 scope. Number drifts only when a new tranche changes OCR'd-page count, which is rare.
2. **`4,111 of 4,161` cleaned-pages count in methodology** — left "4,111" as literal prose; only the right-hand `4,161` was templated. Operator: confirm whether "4,111" should also become a constant (it's recorded somewhere but not in `manifest.json`).
3. **`116` and `162` references from the operator brief** — not found in current `web/src/`. The "162 files" / "116 cards" numbers in the Sprint 1 brief appear to be stale; current corpus is 158 cards / 4,161 OCR'd pages.
4. **Author override on /finds entries** — Article schema currently defaults to `pursue-index` as author; frontmatter schema (`content.config.ts`) has no `author` field yet. If a finds entry should ever credit a named human author, add `author: z.string().optional()` to the schema; `articleJsonLd()` already reads `entry.data.author` when present.
5. **Speakable selectors are minimal** — currently one CSS selector per page (`#methodology-lede`, `#about-lede`, `#cite-lede`) targeting the lead paragraph. If voice-assistant surfaces should read further into the page (e.g. the citation table on /cite), add more selectors per `speakableJsonLd(...)`.

## Saturday-morning pickup (2026-05-16)

**Start here.** Tonight's autonomous run was scoped to tier A + B from the "What can you knock out while I'm out?" decision. Everything shipped clean except one prod-side bug that I caught + fixed in the same run.

What's live on prod that wasn't there when you left:
- **`/timeline`** — new browse surface. Year-axis strip with 123 plotted dots + 35-card "undated" abstention bucket below. Reads `data/display_dates.json` (your 2 approvals) + the agent's 156 tentative proposals. As you do the phase-4 review, the page lights up incrementally.
- **Card-detail "ALSO CATALOGED UPSTREAM AS" section** on the 9 cards with duplicate-card-id alt-titles. Example: `/card/ea029a05470b8f4e` shows PR031/PR032/PR033 cross-references with DVIDS click-throughs.
- **Omnibus reclassification of the proposals queue** — 16 cards (FBI 62-HQ-83894 sections, Box 7 collections, 1940s Generals files, etc.) were rewritten from "agent proposed a single date" to "abstain with templated coverage-range reason." Your review queue is now 120 single-document cards + 16 confirm-abstain (~5 sec each) instead of 158 unfiltered. Estimated review time: 45-75 min instead of 1-2 h.
- **Section 6 (`13f86e95aed52840`) preserved-pin reaffirmation** logged in `data/audit-log.jsonl`. The May-12 OLD-bytes pin stays canonical; NEW upstream bytes are documented as the benign Adobe Paper Capture re-OCR pass per the May-14 finding.
- **Editorial finding** at `pursue-opsec/findings/2026-05-15-incident-date-field-shape.md` generalizing Issue #36 from "specific dates wrong" → "the field's shape is wrong for ~25% of the corpus." Issue #36 closed.

What I detected + fixed mid-run:
- The first `/timeline` deploy worked locally but rendered with **empty data on prod** because I used `node:fs.readFileSync` in the Astro frontmatter — that silently fails in the Cloudflare Pages build context. Switched to native ES imports (matching diff.astro's pattern). Verified live on prod: total 158, approved 2, abstained 35, 123 dots. Documented in commit `8703f2d`.

To resume phase-4 review:

```bash
python scripts/curate_dates_ui.py
# → opens http://localhost:5555/
```

Keyboard: `A` accept · `E` edit · `R` reject · `S` abstain · `J/→` skip. Your existing 2 entries stay (the script doesn't overwrite display_dates.json). 16 cards now propose abstention; you'll fast-confirm those (5 sec each). 120 cards still need a real decision (~30-60 sec each).

**One open editorial decision** carried over: your two already-approved entries are both omnibus files (1940s Generals Vol 1 + Vol 2). Per the new policy, they "should" be abstentions. Editorially defensible either way — you picked dates with cited evidence. Your call whether to leave them as-is or revisit them.

API spend tonight: **$0** (no agent re-runs; all changes via pattern-matching scripts + manual code).

## What Was Just Done

**2026-05-15 (late night, autonomous AFK) — /timeline scaffold + alt-titles UI + omnibus reclassification + display-date-curation phases 1-3 + diff-page full plan + Section 6 re-pin all shipped to prod.**

Six commits pushed (`311e16a..8703f2d`):
1. `08e5088` feat(display-dates): phases 1-3 — schema + writer agent + review UI
2. `f0fd915` chore(display-dates): 2 operator-approved entries from initial curation pass
3. `311e16a` feat(diff): arbitrary snapshot-pair selection + timeline + rename-aware diff
4. `cf52630` feat(curation): pre-classify omnibus-pattern proposals as abstentions
5. `aa6fd75` feat(timeline): /timeline page scaffold reading curated dates + agent proposals
6. `da847cf` feat(card-detail): surface alt-titles for duplicate-card-id cohorts
7. `9b4e974` chore(audit-log): Section 6 preserved-pin reaffirmation after May-14 event
8. `8703f2d` fix(timeline): use native ES imports for date overlay data (CF Pages build)

Tests: 487 pytest + 31 node:test passing (added 11 timeline-helpers + 20 diff-helpers).

Prod QC re-run (divona, 7 suites, 26 scenarios): **0 real failures** post-fix. Two known QC spec stalenesses remain (the VID `[NO ASSET URL]` scenario and diff scenario 3 cardinality) — both are spec-side tightening, not site bugs. Worth ~10 min when you're back.

**Operator-decision queue (updated)**:
1. ~~release-pipeline-gate~~ **shipped**
2. ~~display-date-curation phases 1-3~~ **shipped** (phase 4 = your Saturday review)
3. ~~diff-page-arbitrary-pair-selection (full plan)~~ **shipped**
4. ~~duplicate-card-ids Option 1~~ **shipped**
5. ~~Section 6 re-pin~~ **shipped (LOW item closed)**
6. **Two QC spec stalenesses** — small cleanup
7. **Video integrity in verify-assets-daily.yml** — extends the cron to walk video rows
8. **Schema extension** (two-slot `display_date_incident` + `display_date_document`) — deferred per tonight's finding; revisit once single-document curation reveals boundary cases
9. **incidents-map-clustering (`/map`)** — Tier 2 net-new geographic browse surface
10. **pursue-vision-augment** — Tier 2 Phase 2 VLM extraction

## What Was Just Done

**2026-05-15 (evening) — Tranche c9cc83fcaf43 promoted end-to-end; the May-12 HIGH-priority `release-pipeline-gate` proposal shipped; the public-side scaffolding for an autonomous-finds-pipeline landed (structural validator + CI gate).**

### Tranche c9cc83fcaf43 (accessibility metadata backfill)

158-card metadata-only tranche detected by the 30-min poll workflow at 2026-05-14 20:06 UTC. Zero byte changes. 130 cards got upstream `Image Alt Text`, 131 got DoD `Image VIRIN` identifiers (all `260508-D-D0360-NNNN`, sequential — single upstream batch). Pattern matches the prior 4a35f5596951 metadata-only tranche; not adversarial. Promoted via `pursue ingest run --tranche c9cc83fcaf43`.

Wiring:
- `CardMetadata` schema extended with `image_alt_text`, `image_virin`, `original_classification` (backward-compatible optional fields). Classification is extracted at parse time from alt-text when an explicit level keyword is present (Top Secret / Secret / Confidential / Restricted / Unclassified). 17 of 158 cards have an explicit level recorded.
- `web/src/components/GalleryIsland.tsx` prefers upstream alt-text over auto-generated when present, with the redaction-suffix preserved for screen-reader signal. Falls back to existing title-based alt when alt-text is absent.
- Card detail sidebar now renders the original classification as a badge + the VIRIN as a citable DoD identifier (DoDI 5040.02 format). Rendered on the 17 cards with explicit classification; VIRIN rendered on ~83% of cards.
- `/diff` page: 1-line fix to compare current snapshot against the most recent PRIOR snapshot (was comparing against Release 01 baseline, which made every diff look like a cumulative changelog instead of the per-tranche delta visitors expect).

### Release-pipeline-gate (May-12 HIGH item, now shipped)

Six implementation steps complete:

1. `tests/integration/test_card_page_coverage.py` — every manifest card_id has a built `dist/card/<id>/index.html`
2. `tests/integration/test_alias_destinations.py` — every alias terminal has a built page; alias chains acyclic
3. `tests/unit/test_snapshot_mirror_coverage.py` — pipeline + web snapshot dirs in sync, index.json drift-free, paired snapshots byte-equal, manifest mirror byte-equal
4. `.github/workflows/release-gate.yml` — wires all six AC into a single CI status check on PRs touching manifest / snapshot / aliases / finds paths
5. `.claude/skills/release-pipeline-gate/SKILL.md` — operator-side checklist mirroring the CI workflow for local pre-push verification
6. `pursue ingest run` now invokes `build_video_posters.py` and `build_pdf_thumbs.py` as part of the lockstep refresh (graceful-skip when local inputs are missing — so it runs in CI without harm and adds value operator-side)

This closes the bug class behind the four May-12 hot-fixes (`5e9b480`, `9b9b40d`, `076ef78`, `ffeeddd`, `93873c5`). 482 tests green; 11 of those are the new release-gate suite.

### Finds structural validator (public-side scaffolding)

Public-side surface for a future autonomous content pipeline. The validator at `pursue_index/finds_validator.py` enforces the structural minimum that every `/finds` entry — hand-written or future-bot-opened — must pass:

- Frontmatter completeness (title, summary, tags, cards, published)
- Citation density ≥3 `<Cite>` tags
- Methodology / abstention / provenance section present (matches the varied closing-frame patterns the corpus uses today: "Provenance of this entry", "Why X is in this archive", "What we're not claiming", "What the file establishes", "What to read instead", etc.)

Word count outside 800-5000 surfaces as a soft warning, not a gate failure. CLI runnable: `python -m pursue_index.finds_validator [path...]`. CI-runnable: step 5b of the release-gate workflow on every PR touching `web/src/content/finds/**`. All 21 currently-committed entries pass the gate; the two shortest entries (rhodes 759 words, whats-not-uap 683) surface word-count warnings.

The validator is intentionally bottom-of-the-stack: it doesn't enforce voice, style, or novelty. Those are upstream concerns. It catches the obvious structural failure modes before editorial review burns operator attention.

### Test suite + arch state

- 482 tests passing (467 before today's session + 11 release-gate + 4 finds-validator integration assertions across categories)
- All file-size warnings within the soft band (200 < lines < 400); no hard errors

### Updated operator-decision queue

1. **Release-pipeline-gate** (HIGH from May-12) — **SHIPPED**
2. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — still queued
3. **Re-pin Section 6 `preserved=true`** (LOW) — still queued
4. **Video integrity in `verify-assets-daily.yml` cron** — still queued (registry rows landed on 2026-05-14; cron filter still excludes them)
5. **`/diff` arbitrary-pair selector + timeline strip** (the FULL plan beyond today's 1-line fix) — still queued
6. **display-date-curation** (unblocks `/timeline`) — still queued
7. **autonomous-finds-pipeline** — public-side scaffolding **SHIPPED** today; remainder lives in the private fleet (writer agent, voice profile, novelty filter, bot account) and is not in this repo's scope

## What Was Just Done

**2026-05-14 (late afternoon) — NAS preservation tier rebuilt to mirror the public R2 layout prefix-for-prefix + 28 DVIDS-sourced video assets added to the preservation chain across all three storage tiers.**

The NAS-layout decision item queued earlier in the day is now resolved. NAS now mirrors primary R2 exactly:

- `archive/<byte_sha256>.<ext>` — content-addressed pool, immutable by construction; an `rclone sync` against the public bucket cannot overwrite a key because the filename IS the sha
- `<card_id>.<ext>` — current-pointer for PDFs/images (matches R2 root keys)
- `<dvids_video_id>.mp4` — current-pointer for videos (DVIDS video ID is the unique key since multiple cards can be paired with the same video)

Hardlinks tie the two views to the same inodes; storage cost = unique inodes only. The threat scenario from this morning's handoff (a future naive rclone overwriting OLD → NEW on the NAS) is structurally eliminated — `archive/<sha>` keys can never collide across byte versions.

**28 DVIDS videos preserved**. Mapping (`card_id` ↔ `dvids_video_id` ↔ `DOD_<asset_id>.mp4`) was recovered from the public DVIDS pages, and bytes were ingested from operator-side local copies. All 28 are now in:

- Primary R2 (`archive/<sha>.mp4`, IfNoneMatch immutable, hash-verified post-upload)
- Backup R2 (direct copy from primary, hash-verified)
- NAS (hardlinked into the same r2-mirror layout, hash-verified)

`data/asset-bytes-registry.jsonl` was extended with 28 new rows. Schema additions (backward-compatible): `source: "dvids"`, `dvids_video_id`, `dod_asset_filename`. `current_key` is omitted on video rows because videos are served via DVIDS iframe embeds on the public site, not an R2 alias. The backup-mirror script in `pursue-opsec` was updated to gracefully handle archive-only rows.

**Preservation guarantee state as of today:**

| Asset class | Archived byte versions | Storage tiers |
|---|---|---|
| PDFs / images | 200 | primary R2 + backup R2 + NAS |
| Videos (DVIDS) | 28 | primary R2 + backup R2 + NAS |
| **Total** | **228** | **3-place redundancy across the board** |

Registry rows: 230 (202 pre-existing + 28 video).

**Operator-decision queue (updated):**

1. **Release-pipeline-gate proposal** (HIGH from May-12) — still queued.
2. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — still queued.
3. **Re-pin Section 6 `preserved=true` (LOW)** — re-pin against the new sha OR affirm the old pin via audit-log.
4. **Integrate video integrity checks into the daily verify cron** — `verify-assets-daily.yml` currently only walks PDF/IMG cards (those have war.gov URLs to HEAD-check). Video rows are in the registry but the cron doesn't touch them. Closing this loop would extend the daily integrity guarantee to videos as well.

**Closed today (no longer pending):**
- NAS layout decision → resolved (above)
- Old NAS per-card_id paths cleanup → resolved (removed; content preserved via hardlinks)
- Operator-side NAS rsync recipe → doc updated to describe the new layout

> Last updated: 2026-05-14 (afternoon — 70-card event RE-CLASSIFIED as non-adversarial upstream re-OCR; preservation verified across 3 storage tiers)

## Read this first

Today's investigation overturned yesterday's classification. The
"silent redaction event" headline from the morning handoff was
**wrong**. It's not a redaction; it's an upstream re-processing pass
(Adobe Acrobat Paper Capture: re-OCR + rotation correction +
accessibility tagging). Same image content, added text layer, better
metadata. 3-place storage redundancy confirmed for OLD bytes. See
**`pursue-opsec/findings/2026-05-14-70-card-upstream-event-classification.md`**
for the full classification + preservation verification.

## What Was Just Done

**2026-05-14 (afternoon) — Deep dive on the 70-card byte event. Re-classified as benign upstream re-OCR, not adversarial redaction. All preservation guarantees verified across 3 storage tiers (primary R2, backup R2, NAS). Issues #60/#61/#62 closed.**

Investigation summary:
- **Spot-checked 8 of 70 affected cards** spanning all 4 agencies (FBI, DOW, NASA, State), full size-change distribution (-86% to +227%), and both already-Adobe-processed and previously-scan-only files. Every NEW PDF has identical signature: `Producer: Adobe Acrobat (32-bit) 26 Paper Capture Plug-in`, `Tagged: yes`, real OCR text layer, rotation-corrected. Every card has **identical page count** old vs new.
- **Sampled page renders** at 150 DPI for Section 1 page 70 (Wyly teletype) and Section 6 page 135 (Eekhout interview): pixel-level diffs are diffuse anti-aliasing artifacts (mean 3.28–6.84 / 255), no localized clusters indicating word swaps or in-place redactions. Content visually preserved.
- **OCR comparison**: Surya (our pages.json) is markedly cleaner than Adobe Paper Capture's embedded text on these teletype-style scans. "Free re-OCR via pdftotext" path rejected.
- **Preservation verified across 3 tiers:**
  - Primary R2 (immutable via IfNoneMatch): 140/140 keys present, sizes match
  - Backup R2 (separate bucket): 140/140 keys present + 5 OLD shas hash-verified (847 MB streamed)
  - NAS (`/mnt/nas/personal/pursue/pdfs/`): 70/70 affected cards hold OLD byte size, 4 hash-verified MATCH
- **Issues closed:** #60 (silent-overlay-detected → re-classified upstream re-OCR), #61 (preserved-tampered → upstream re-issue, not control-plane tampering), #62 (transient poll-failure, 5 consecutive successful runs since).

**Operator-decision items now queued (priority order):**

1. **NAS layout decision (NEW, MEDIUM)**: Current NAS layout is `pdfs/<card_id>/<filename>.pdf` — one file per card_id, no sha namespacing. OLD bytes are currently preserved on NAS only because no rsync ran post-event. A future naive sync would overwrite OLD → NEW, dropping the third copy. Two options: (a) adopt per-sha layout matching the rsync-setup recipe doc; (b) freeze a dated tar.gz of current `pdfs/` before any future sync.
2. **Release-pipeline-gate proposal (still HIGH from May-12)** — `pursue-opsec/findings/2026-05-12-release-pipeline-gate.md`, untouched.
3. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — unchanged.
4. **Re-pin Section 6 preserved=true (LOW)**: Either re-pin against the new sha (`7620094802…`) or affirm the old pin (`3df0935c…`) with an audit-log entry. Either is fine; the OLD bytes are already in 3 places.

**What did NOT happen** (vs the morning handoff's queued items):
- No public "redaction event newsletter" — the underlying premise was wrong.
- No re-OCR of the 70 cards via pdftotext — Adobe's text layer is lower quality than our Surya.
- No editorial response to the redaction — there was no redaction.
- No commits/code changes — investigation was read-only.

**2026-05-14 (mid-day) — Operator returned after 2-day quiet stretch. Discovered (via status pull) that the integrity layer captured a major upstream silent-redaction event overnight 2026-05-13/14: 70 cards' bytes silently changed at the same upstream URLs, total corpus shrank 2.34 GB → 1.10 GB (-53%). Both versions preserved in R2 + backup R2. [SUPERSEDED — see today's afternoon entry above]**

Headline metrics:
- 70 of 132 archived cards had bytes change at the same URL between 2026-05-12 (last archive run) and 2026-05-14 07:16 UTC (daily verify cron)
- Top drops: FBI 62-HQ-83894 Section 6 (371 → 61 MB, -310 MB), Box 7 Incident Summaries 1-100 (247 → 33 MB), Box 7 101-172 (243 → 29 MB), every FBI 62-HQ-83894 section reduced
- 41 of the 70 are FBI; 21 "Other" (mostly Box 7); 4 NASA; 2 State; 2 DOW

Issues filed by the integrity layer (all healthy behavior):
- #60 silent-overlay-detected — the 70-card event
- #61 preserved-tampered — Section 6's pinned sha no longer matches current-pointer (correctly raised; the upstream re-edit overwrote the bytes after our May-12 restoration pin)
- #62 poll-failure — single transient at 10:16 UTC, recovered next cycle, closeable

**The integrity layer worked exactly as designed.** Both old + new bytes preserved at content-addressed `archive/<sha>.<ext>` keys. Backup R2 mirror has both. Daily verify cron caught the change within hours of upstream's edit. This is the project's first real defense of its preservation guarantee against the threat model the operator articulated at the start.

**Operator-decision items queued** (next session priority):
1. Editorial response to the redaction — re-OCR? UI surface? public messaging?
2. Section 6 specifically — the May-12 finds entry (`fbi-1947-dallas-teletype.mdx`) cites Section 1 page 70 (Wyly teletype); Section 1 also redacted (109→30 MB); verify the cited page survives
3. Release-pipeline-gate proposal still open (HIGH from yesterday)
4. duplicate-card-ids Option 1 (alt-titles UI surface)

Full backlog ranking in last session's state.md entry below; full event detail in the handoff doc.

**2026-05-13 (overnight, second tranche ingested + deep audit clean)**

## What Was Just Done

**2026-05-13 (~04:15 UTC) — Tranche 4a35f559 ingested cleanly + deep cross-tranche byte audit CLEAN + plans dir cleaned per operator policy.**

Second-wave upstream catalog cleanup detected at 18:13 UTC (issue #57, since closed). 0 added/removed/quarantined/restored, 46 field-only changes (PDF-card title format updates: Section_5→Section_005, B4→B008, etc.). asset_urls + asset_filenames stable so card_ids preserved + NAS files untouched. First end-to-end test of the `promote_snapshot` deeper-fix patch (`ffeeddd`) on a fresh tranche — auto-mirrored cleanly to all three deploy paths.

**Deep cross-tranche byte audit (165 card_ids × 4 snapshots): CLEAN.** Registry byte_sha consistency 0 mismatches; asset_url drift 0; Section 6 restoration byte-identity reconfirmed against audit-log; field-only spot-check confirms title-format-only changes. Read-only investigation, no API budget, no upstream re-fetches. Findings at `pursue-opsec/findings/2026-05-13-deep-byte-review-4a35f559.md`.

**Plans dir cleaned (operator directive: don't retain shipped plans).** 8 shipped plans deleted (a11y, auto-poll, card-rename, curated-finds, doc-staleness, llm-cleaned-pilot, llm-cleaned-text, visual-browse-surface). Git history is the audit trail. Remaining: 8 backlog plans + 5 tranche-diff artifacts.

**2026-05-13 (~02:00 UTC) — Both autonomous-run PRs MERGED. Plus 4 hot-fix commits on main. Plus deeper-fix patch. Plus opsec proposal for a release-pipeline gate. Final staleness sweep clean.**

## What Was Just Done

**2026-05-13 (~02:00 UTC) — Both autonomous-run PRs MERGED. Plus 4 hot-fix commits on main. Plus deeper-fix patch. Plus opsec proposal for a release-pipeline gate. Final staleness sweep clean.**

**Merged tonight:**
- **PR #58** staleness-remediation (`merged 01:50 UTC`) — 31 audit findings + 2 Codex P2 nits + 3 plans marked shipped. Rebased once.
- **PR #59** accessibility-remediation (`merged 01:58 UTC`) — WCAG AA: 1 critical+28 serious+60+ moderate → 0 violations; new AtlasAccessibleBrowser; new contrast-test suite. Rebased twice (post-#58 + post-hotfixes).

**Hot-fixes on main (all symptoms of one structural gap):**
- `5e9b480` — sync `web/src/data/manifest.json` from pipeline manifest (was causing prod 404s on PR-renamed card pages)
- `9b9b40d` — root-cause patch in `promote_snapshot()` for the manifest mirror
- `d84b792` — restore 16 video posters at new card_ids + Section 6 PDF thumb
- `076ef78` — mirror tranche-65572b38 snapshot to web-side so /diff page compares correct pair
- `ffeeddd` — extend `promote_snapshot()` to also mirror snapshot + rebuild web-side index.json
- `93873c5` — final staleness sweep (3 more user-facing numerics: whats-not-uap, apollo-17, cite-this.md)

**Operator-stated structural fix (HIGH priority for next session):** `pursue-opsec/findings/2026-05-12-release-pipeline-gate.md` — proposes a deterministic CI-enforced GitHub Action + bpsai-pair skill that gates merges without confirming all deploy-side mirrors are in lockstep with the pipeline-side source-of-truth. Tonight's four hot-fixes are all the same class of bug. Concrete plan: 6 implementation steps, ~2.5-3 hours. Recommended top-of-backlog before the next tranche.

**Discovery flagged for editorial decision (not blocking):** `pursue-opsec/findings/2026-05-12-duplicate-card-ids-discovery.md` — tranche 65572b38 has 9 unique card_ids that appear multiple times because upstream reuses one PDF's `asset_url` across multiple "cards" with different titles. 12 collapsed instances. Three remediation options laid out; recommendation Option 3 (post-parse disambiguation, backward-compatible).

**Live deploy verified:** all key URLs return 200; / shows 4,161 pages; /atlas shows 4,127 dots; /diff references 65572b38.

**2026-05-12 (overnight) — WCAG 2.2 AA accessibility audit + remediation across the entire site. Branch: `accessibility-remediation`. axe-core scan: 0 violations across 18 representative routes (all pages + a representative card detail page).**

Implements `.paircoder/plans/accessibility-audit-and-remediation.md` end-to-end. Operator constraint: fix everything, defer nothing. Outcome:

- **Color contrast (WCAG 1.4.3).** `--color-text-faint` (#4a5563) was failing AA on every background (2.06–2.57:1, 152 usages). `--color-text-dim` (#6b7783) only met large-text. Bumped to `#8390a0` / `#9ba6b3` — minimum changes that hit AA on every surface while preserving the dim < faint < text < bright hierarchy. Atlas legend swatch for "UNKNOWN" updated in lockstep (`atlas-helpers.ts`). Drift guarded by new pytest `tests/unit/test_a11y_contrast.py` (38 parametrized cases + a token-table-vs-CSS sync check).
- **Skip link (WCAG 2.4.1).** `Base.astro` now ships a `.sr-only-focusable` skip-to-main link as the first focusable element on every page. Visible-on-focus, signal-green styling, 9999 z-index.
- **Atlas accessible alternative (WCAG 1.1.1 for the WebGL canvas).** New `AtlasAccessibleBrowser.tsx` companion island renders the corpus as a sortable HTML table with `aria-sort` headers, agency/date view toggle, and free-text filter. Keyboard- + screen-reader-friendly path to the same `/card/<id>` destinations the canvas dots link to. The canvas itself now carries `role="img"` + `aria-label` + `aria-describedby` pointing at an `.sr-only` long summary built from the manifest's per-agency counts.
- **Form labels.** Chat textarea now has an `<label for="chat-input">` (sr-only). Every `<select>` in `CardExplorer` is now wrapped by `<label>` + carries `aria-label` (was previously orphaned). `SearchFilterRail` uses `<fieldset>` + `<legend>` for the agency-pills group and the date-range group instead of a `<p>` "label" sibling.
- **Live regions.** Chat transcript: `role="log" aria-live="polite"`. Phase indicator (RETRIEVING/GENERATING): `role="status"`. Search results count: `aria-live="polite" aria-atomic="true"`. Atlas + search loading states: `role="status"` with sr-only "Loading…" text. Error states: `role="alert"`.
- **Heading hierarchy.** 404 page now has an `<h1>` (sr-only — the visible "shell error" block stays as decoration with `aria-hidden`). Card sidebar `<h3>`s for ASSET / CROSS-REFERENCES / OCR TEXT promoted to `<h2>` (siblings of the SOURCE h2 under the card h1). Finds-entry "Sources" promoted from `<h3>` to `<h2>`.
- **Decorative aesthetic.** Every `$ grep -ri ...` shell-prompt header is `aria-hidden="true"` (decoration; the meaningful h1 sits directly below). Top scanline div, breadcrumb `/` separators, gallery dots, atlas legend swatches all `aria-hidden`. Chat gear emoji wrapped in `aria-hidden`.
- **Nav semantics.** Primary nav has `aria-label="Primary"` and the active link carries `aria-current="page"`. Breadcrumbs on `/card/<id>` and `/finds/<slug>` have `aria-label="Breadcrumb"` + `aria-current="page"` on the leaf. GH external link has `aria-label="…(opens in new tab)"`. Per-removal-event link rows on `/removed` switched from `<nav>` to `<div>` to avoid duplicate-landmark axe violations.
- **Alt text.** Gallery image alts now include "(contains redactions)" when the underlying card is redacted, so screen readers get the same signal sighted users get from the visible REDACTED corner badge.
- **Global focus-visible ring.** Added to `global.css` for `a` / `button` / `[role="button"]` / `[role="tab"]` / `summary` so custom-styled buttons that don't define their own ring still surface focus visibly.

**Verification:**
- `cd web && npm run build` — clean, 181 pages built
- `pytest tests/unit/ -q` — 443 passed, 2 deselected
- axe-core/Puppeteer scan over 18 routes — **0 violations of any severity, including best-practice tags**
- `bpsai-pair arch check tests/unit/test_a11y_contrast.py` — clean

**Operator-decision item carried in commit message:** the `--color-text-faint` / `--color-text-dim` bumps shift two tokens used on every page. Visual diff is small (still distinctly dim) but worth a sanity-check on a few representative surfaces before merging.

Findings file lands at `pursue-opsec/findings/2026-05-12-accessibility-remediation-results.md` in the operator opsec repo.

**2026-05-12 (late evening) — Card-rename plan COMPLETE (steps 1-7). Tranche 65572b38 ingested + promoted. Surgical v1.0.0/numeric-drift fixes on the highest-traffic public surfaces. Backlog re-prioritized.**

Steps 6 + 7 of the card-rename plan landed:
- **Step 6**: `tests/unit/test_finds_citations.py` — CI test asserts every `<Cite card="...">` (and `cards:` frontmatter) in `web/src/content/finds/*.mdx` resolves via current manifest, /removed, or alias chain. 3 tests including alias-chain-acyclicity defense. **Caught one real broken citation on first run**: `fbi-62-hq-83894-section-6-removed-2026-05.mdx` cited `9c86c04b5e4a50e8` (the no-asset_url Section 6 transient mid-state from the 0d7e9ba1 tranche). Fixed by adding an operator_manual alias `9c86c04b → 13f86e95` (the canonical Section 6 card_id) to `data/card-aliases.json`. Now 17 aliases live; CI green.
- **Step 7**: `pursue ingest run` orchestrator (`src/pursue_index/ingest_run.py` + CLI) — gate-checks the tranche, locates the snapshot, promotes to `latest.json`, identifies which downstream stages need to run based on tranche-diff classifications. For 65572b38 (metadata-only): just promote + rebuild deploy mirrors via `cd web && npm run build`; no OCR/embed work needed. 9 unit tests, all green. Also added prefix-matching to the gate's sha lookup so CLI invocation with the 12-char display prefix works.

**Tranche 65572b38 ingested**: `data/manifests/latest.json` is now the new snapshot. Astro build clean: 181 pages.

**v1.0.0 / numeric-drift surgical fixes** on the highest-traffic surfaces:
- `web/src/pages/methodology.astro`: "Research preview (v1.0.0)" → "(v1.1.0)"; loosened framing
- `web/src/layouts/Base.astro`: "v1.0.0 preview" / "v1.0.0 calibration" → drop version-specific framing
- `web/src/pages/index.astro`: "4,153 PAGES" → "4,161 PAGES"
- `web/src/pages/atlas.astro`: "4,119 OCR'd pages" → "4,127"
- `README.md`: "4,153 OCR'd pages spanning the 116 PDF cards in Release 01" → loosened to avoid future drift
- `docs/architecture.md`: "161 in Release 01" → "158 in PURSUE Release 01 (as of tranche 65572b38)"
- The comprehensive 31-finding sweep is what `pursue-opsec/findings/2026-05-12-documentation-staleness-audit.md` covers — recommended as the next priority work.

**Backlog re-prioritized** (in "What's Next" below). Recommended #1: documentation staleness remediation. Already-scoped findings, low-risk, high editorial-credibility return.

**Editorial accuracy correction** that came out in this session: I had earlier characterized FBI Photo B-series and State Cable 004 as net-new content in tranche 65572b38, based on a shallow CSV diff. That was wrong. The proper card_id-based tranche_diff shows 0 net-new content in this tranche; both FBI Photos and Cables were already in the prior 0d7e9ba1 tranche with slightly different titles/URLs that the shallow diff treated as added/removed pairs. Corpus is at 158 cards in upstream + 3 on /removed = 161 unique cards = matches the original May-8 count exactly. No content lost across the entire history.

**2026-05-12 (evening) — First end-to-end tranche approval ran clean for 65572b38. Audit re-verified FBI Section 6 byte-identity; 16 PR-card renames materialized to card-aliases.json.**

`pursue ingest approve` executed against tranche 65572b38 with all 16 quarantined → operator_manual rename pairings. The pre-approval TOCTOU audit re-fetched FBI 62-HQ-83894 Section 6 from upstream (~370MB, ~10s actual runtime), confirmed byte_sha256 still matches the morning's pin (`3df0935cf48e6847d0a5df77a987f8a446e545cc1dda20cad60f79d966516568`), and emitted summary `ok: 1, skipped: 16`. Approval recorded; 16 alias rows written to `data/card-aliases.json` with operator_manual provenance; full audit row appended to `data/audit-log.jsonl`.

This is the first time the integrity stack has run end-to-end against a live upstream change with operator approval. The full chain held: poll detected the rename → byte-archive captured every byte stream → tranche-diff classified the 158 cards → side-by-side metadata review confirmed all 16 PR renames as clean → audit re-verified the restoration → approval clean → aliases materialized. The worker resolver shipped in step 2 will redirect `/card/<old_id>` for all 16 + Section 6 from the next deploy.

Open follow-up: full `pursue ingest run` (manifest promotion + OCR/embed/clean + deploy rebuild) for tranche 65572b38. Currently the deployed `latest.json` is still the prior `0d7e9ba1` snapshot; the approval clears the gate but doesn't auto-promote. Step 7 of the card-rename plan covers the orchestration.

**2026-05-12 (evening) — Post-ingest TOCTOU audit (plan step 5) shipped. `pursue ingest approve` now runs an inline pre-approval re-fetch audit; refuses approval on any sha mismatch.**

Step 5 of the card-rename plan landed. New `pursue_index.post_ingest_audit` module re-fetches upstream bytes at approval time for every byte-collision rename and every restored_unchanged event, compares against the sha recorded at tranche-diff time, and surfaces any mismatch as a blocking error before aliases are materialized. 9 unit tests, all green; arch-clean.

The audit catches the TOCTOU scenario: upstream serving bytes A during tranche-diff and bytes B during approval — turning a confirmed safe-to-alias event into a content swap done under cover of metadata change. Three target classes:

- `byte_collision_rename` (Class A) — expected_sha is from tranche-diff; refusal on mismatch
- `restored_unchanged` (Class D) — expected_sha is the pinned byte_sha from the registry; refusal on mismatch
- `operator_manual_rename` (Class C approved) — typically no asset_url (PR/VID metadata-only cards); skipped with note when no asset_url is present, sha recorded for audit trail otherwise but never refused

Wired into `pursue ingest approve` with a `--skip-audit` escape hatch for emergency cases. Audit results are appended to `data/audit-log.jsonl` for permanent provenance. The `--snapshots-dir` flag locates the candidate manifest snapshot needed to look up asset_urls.

Characterization helpers (OCR-text diff, PDF metadata diff for `restored_modified` investigation) deliberately deferred — no `restored_modified` or differing-byte Class C entries in the current tranche to warrant the build.

For the current `65572b38` ingest, the audit will re-fetch ONE card (FBI 62-HQ-83894 Section 6, ~370MB, ~30s) to verify the restoration is still byte-identical at approval time. The 16 operator_manual aliases all have null asset_urls and will be skipped automatically.

**2026-05-12 (early evening) — Ingest-approval gate (plan step 4) shipped. `pursue ingest approve` / `pursue ingest check` CLI live, integrated into the existing typer CLI.**

Step 4 of the card-rename plan landed. New `pursue_index.ingest` module with the gate primitives (`is_tranche_approved`, `record_approval`, `auto_approve_renames`, `parse_rename_flags`, `append_aliases`) and `pursue_index.cli.ingest_cli` typer wrapper exposing `pursue ingest check` and `pursue ingest approve`. 16 unit tests, all green; arch-clean.

The CLI:
- `pursue ingest check --tranche <sha>` returns exit 0 if approved, 1 if not. Downstream ingest-pipeline commands call this gate to refuse to proceed against an unapproved tranche.
- `pursue ingest approve --tranche <sha> --note "..." [--approve-rename <new>=<old>]...` records an audit-log row and materializes the approved aliases into `data/card-aliases.json`. Class A entries (byte-collision-confirmed renames) are auto-included; Class C / quarantined entries require explicit `--approve-rename` flags. The CLI surfaces a warning if any quarantined items go unaddressed (gate still clears, but those renames are NOT in aliases.json — operator must come back if/when they decide).

Approval-log infrastructure at `data/tranche-approval-log.jsonl` (append-only, JSONL, corrupt rows skipped on read). Failure-mode discipline: missing log → unapproved; corrupt rows → skip; malformed `--approve-rename` flags raise ValueError so operator notices before writing a broken alias. The `byte_collision` vs `operator_manual` method field distinguishes cryptographically-confirmed from operator-judgment renames in the audit trail.

The first real exercise of the gate against tranche `65572b38d27c` (which has 0 Class A + 16 quarantined + 1 restored_unchanged) is the operator-driven next step — pending review of the 16 quarantined.

Editorial note baked into the design: a different byte_sha means *something changed* — re-render, metadata edit, font subset shift, redaction-layer update, or genuine content edit. The integrity layer detects change; it does not characterize it. Step 5 (post-ingest tampering audit) will add characterization helpers (OCR-text diff, PDF metadata diff, page-count delta) that turn "sha changed" into "here are the specific differences, you decide." Approval-CLI messaging deliberately avoids "tampering" / "malicious" wording when surfacing `restored_modified` items.

**2026-05-12 (late afternoon) — `tranche_diff.py` (plan step 3) shipped + restoration-class detection (Class D) added on first real-world exercise.**

Step 3 of the card-rename plan landed. New `scripts/tranche_diff.py` (326 lines) + supporting helpers in `src/pursue_index/tranche.py` (heuristics, levenshtein, numeric-id extraction) and `src/pursue_index/tranche_report.py` (markdown + JSON rendering). 31 unit tests, all green; arch-clean.

Classifies every added card_id in an incoming tranche into one of six classes:
- **A** confirmed rename (byte_sha collision against existing registry entry → safe to alias)
- **B** net-new content
- **C** quarantined (no collision, but title-continuity heuristics match an old card → manual review)
- **restored_unchanged** previously-archived card_id reappears with byte-identical content (safe)
- **restored_modified** previously-archived card_id reappears with DIFFERENT bytes (possible tampering disguised as restoration — manual review)
- **restored_unknown** previously-archived card_id reappears but no asset_url to verify

The restoration class wasn't in the original plan; surfaced during first real-world exercise against the live `65572b38` tranche when FBI 62-HQ-83894 Section 6 (`13f86e95aed52840`, the card pinned to /removed earlier today) showed up in the new manifest as "added." The threat model explicitly names this scenario ("re-publication after removal as cover for content edits"), so added the detection logic + tests + report sections in the same commit.

First real-world dry-run against `65572b38` (heuristic-only, no byte-sha fetches): **0 confirmed renames, 16 quarantined, 1 restored_unknown (FBI Section 6), 17 removed, 93 field-only changes**. The 16 quarantined are PR40↔PR040-style zero-padding renames that will mostly resolve to Class A once we run with real byte fetches. The 1 restored_unknown will resolve to either `restored_unchanged` (safe — same bytes we pinned) or `restored_modified` (SUSPICIOUS — possible tampering). The 17 removed are the old-format predecessors of the quarantined renames.

**2026-05-12 (afternoon) — Three new finds entries shipped + card-rename handling plan adopted + audit-findings sensitivity-routed to opsec + worker alias resolver (plan step 2) live.**

Step 2 of the card-rename plan landed (worker alias resolver). New module `worker/aliases.js` (141 lines) loads `data/card-aliases.json` from the static-assets binding, builds an in-memory lookup map honoring append-only semantics (latest entry wins per old_card_id; `operator_revoke` removes the alias; subsequent rows re-establish). 18 unit tests + 8 integration tests (in `worker/tests/`); 108 worker tests total now pass.

Wired into `worker/index.js`: `/card/<old_id>` 301s to `/card/<new_id>` with `X-Pursue-Aliased-From` header before falling through to ASSETS; `/pdf/<old_id>.pdf` continues to serve preserved bytes from R2 at the old key and stamps `X-Pursue-Aliased-To` header (preservation contract — never redirect PDFs, always serve at the original handle and signal the new identity via header). Failure-soft: a corrupt/missing aliases file silently yields an empty index, never affecting non-aliased requests.

Initial empty aliases file (`{"aliases": []}`) deployed at `data/card-aliases.json` (source) and `web/public/data/card-aliases.json` (bundled into Astro build). Worker is deployable today with the empty file — does nothing until tranche_diff (plan step 3) starts writing alias rows. Astro build clean: 181 pages.

Editorial side-effect: caught a YAML quoting bug in the new Apollo 11 finds entry (`1969` unquoted parsed as int, breaking the content-collection schema). Fixed alongside this commit.

**2026-05-12 (afternoon) — Three new finds entries shipped + card-rename handling plan adopted + audit-findings sensitivity-routed to opsec.**

Three curated finds entries written and editorially approved, document-first (no external-narrative framing): `fbi-1947-dallas-teletype.mdx` (Wyly+Hottel disambiguation in FBI 62-HQ-83894), `fbi-usper-2025-orb.mdx` (modern FD-302 vs MISREP grammar contrast), `apollo-11-debriefing.mdx` (the in-conversation reasoning arc on three distinct anomalies, with cosmic-ray-flashes as the document's strongest physical-science moment). Earlier-draft rebuttal framing scrubbed.

**Card-rename handling plan landed** at `.paircoder/plans/card-rename-handling.md`. Codifies the three-class trust hierarchy (confirmed rename via byte_sha collision / net-new content / suspicious replacement quarantined). Critically distinguishes the always-on capture layer (poll + byte-archive + tranche-diff + daily verify, all unattended-safe) from the operator-gated editorial-publication layer (`pursue ingest run` with tranche-approval). All four open questions resolved: (1) always quarantine Class C, no auto-approval rule; (2) old card_ids preserved forever via append-only aliases — codified as a contract section; (3) bandwidth acceptable; (4) per-card pill on detail page, no new nav surface.

**Documentation-staleness audit findings (31 items) moved** to `pursue-opsec-staging/findings/2026-05-12-documentation-staleness-audit.md`. Audit plan itself stays public (describes the approach, not the current weaknesses). General policy adopted: plans describing how the system works → public; audit findings revealing current weaknesses → opsec until remediated.

**2026-05-12 (mid-day) — Closed the /removed integrity gap + caught the upstream CSV rename + tier-1 backup mirror first-sync verified.**

Operator-driven session: started from the question "where did the May 8 R2 uploads go and are all bytes accounted for?" Built a read-only reconciler (`scripts/r2_reconcile.py`) that diffed the R2 bucket against the asset-bytes-registry. Found exactly **3 orphan objects** — all corresponding to the 3 cards on `/removed` (FBI Section 6, DOW-UAP-D20, NASC-State). These had been uploaded May 8 as part of PR #27's bulk-load and were never brought under the integrity-layer's coverage when the byte-archive stack landed overnight May 11→12.

Closed the gap:

- **`scripts/r2_pin_removed.py`** (with TDD: 6 unit tests, mock-S3-client). Walks `removed-cards.json`; for each card: HEADs R2 → GETs current-pointer bytes → computes byte_sha256 → PUTs to `archive/<sha>.<ext>` with `IfNoneMatch: "*"` (append-only) → appends a registry row with `preserved: true`. Idempotent. Live run pinned 2 archive entries (D20, FBI Section 6) and reported `archive-existed` for the State memo (see byte-finding below).
- **`scripts/r2_verify_preserved.py`** (with TDD: 5 unit tests). Companion to the manifest-walking verify cron — re-reads each preserved card's bytes from R2 and compares against the pinned byte_sha. Different threat model from silent-overlay-detected: this catches in-control-plane tampering (leaked write key, buggy script, accidental wrangler PUT).
- **`.github/workflows/verify-assets-daily.yml`** extended with a new `verify-preserved` step + new `preserved-tampered` issue label/title with full sha-diff body when a preservation copy mismatches.

**Editorial finding surfaced by the integrity layer itself.** The pin's IfNoneMatch returned `PreconditionFailed` on the NASC-State card (`aa3097b4c549a67a`): the archive key already existed because **current-manifest card `9e2c2621d67dde12` has byte-identical content**. Same pattern as yesterday's D20 refutation. The "1963 → 1952 file-swap" framing was incomplete: upstream's 2026-05-11 change to that listing was actually **two operations at once** — (a) re-issued the same 1963 NASC memo at a corrected 1963-coded title (byte-identical, cryptographically verified), and (b) added a genuinely-new 1952 State memo at the original 1952-coded title. The 1963 content was preserved verbatim across the rename. Finds entry `nasc-state-extraterrestrial-policy-memo-1963.mdx` updated with a new "Byte-level integrity finding" section, a corrected preservation table (now 3 cards), and a sentence in provenance about how the tooling discovered the identity.

**Tier-1 durability mirror verified.** Manually triggered `mirror-to-backup-r2` workflow in `pursue-opsec` after operator set the 7 backup R2 secrets. First sync: **129 archive_copied + 129 current_copied, 0 failures, ~13 minutes for ~6 GB.** Tier-1 cross-account redundancy is now live. The 3 newly-pinned preserved entries weren't in this sync (they were uncommitted at trigger time) — re-trigger queued for after this commit pushes.

**Upstream CSV rename caught and patched.** During the session, the operator noticed three consecutive poll-workflow failures (15:28, 16:20, 17:15 UTC) and asked. Investigation: war.gov restructured the UAP site and renamed `uap-csv.csv` → `uap-release001.csv`. The old URL now 404s; the new URL is linked from `war.gov/UFO/` and serves the same 158-card content with the same shape. The naming pattern (`release001`) strongly suggests upstream is moving to **explicit release versioning** instead of mutating a single canonical CSV — actually a *better* upstream model. One-line fix to `csv_url` default in `src/pursue_index/config/settings.py`; 35 existing CSV/poll tests still green. Auto-filed `tranche-poll-failure` issue #55 will close on the next successful poll tick after push.

**Reconciliation final state**: 0 orphans, 0 missing, 263 R2 objects all accounted for by 132 registry rows (3 of which are preserved entries; 1 archive key is shared between aa3097b4 and 9e2c2621 because their bytes are identical).

**2026-05-12 (overnight, ran through morning) — Archive integrity stack + /gallery complete + repo cleanup + reviewer cycle + OPSEC hardening + replacement-card pipeline + VID playback.**

The session ran from sunset through to ~1 AM operator-time the next day. Headline: v1.1.0 shipped at the midpoint; second half was reviewer cycle, security hardening, operator-private companion repo (`pursue-opsec`), tier-1 durability infrastructure, and the catch-everything-at-the-end items the operator surfaced (VID playback was a real bedtime blocker; OCR-deployment drift was a real subtle gap that none of the green-checkmark workflows caught).

Late-session additions on top of the v1.1.0 release notes:

- **`pursue-opsec` private companion repo created (`BPSAI/pursue-opsec`)** with README + findings/2026-05-12-reviewer-cycle.md + reference/{thresholds,trust-boundaries,data-schemas,nas-rsync-setup,r2-destructive-edit-test}.md. SECURITY.md on the public repo got a new "Internal disclosure policy" section codifying that security findings go private, never public issues. Four reviewer-cycle public issues deleted retroactively (#49 patched + closed by commit, #50/#51/#52 deleted from public, content preserved in pursue-opsec).
- **OPSEC hardening on the public repo**: branch protection on `main` (force-push + deletion blocked, enforce_admins=false so bot can still push), wiki + projects disabled, R2 archive PUTs now use `IfNoneMatch: "*"` for atomic immutability. Public forks couldn't be disabled (GitHub policy on public repos). `pursue-opsec` got branch protection + forks-off + wiki/projects-off as belt-and-suspenders.
- **Tier-1 durability** wired in `pursue-opsec`: `mirror_to_backup.py` + workflow that mirrors `pursue-pdfs` → a backup R2 bucket (different account preferred) on a daily 08:13 UTC cron. Hash-pinned boto3 via `requirements-mirror.txt`. Graceful-exit on missing creds. Operator-side NAS rsync recipe at `reference/nas-rsync-setup.md` (rclone config + cron template + quarterly encrypted-snapshot recipe). Tier-2 cryptographic signing of registry rows filed as RFC issue `pursue-opsec#1` for discussion.
- **VID playback fixed** (`70e51f5`). All 28 VID cards have `asset_url: null` (DVIDS-hosted), so the card detail page was hitting `[NO ASSET URL]` for every video. Added `isVideo` branch that renders a `https://www.dvidshub.net/video/embed/<id>` iframe with "Open on DVIDS ↗" fallback. CSP `frame-src` extended to allow DVIDS. Mobile playback via the DVIDS player works post-deploy.
- **Replacement-card pipeline completed** (`4959ff3`). When OCR auto-ran for the new D20 + State memo replacement cards on the 11th, the per-card NAS outputs landed correctly but the deployed mirrors (pages.json, pages-cleaned.json, embed_index.json, embeddings.bin, atlas-layout.json) were never rebuilt — operator caught this when noticing the D20 finds entry's "OCR pending" placeholder. Ran `pursue clean run` on the 2 new cards (~$0.02 Anthropic spend), rebuilt all five deployed mirrors. **Empirical editorial finding from the side-by-side**: the "tradecraft scrub" hypothesis on D20 is REFUTED — original and replacement both carry the same sensitive markers (77 EFS, OEPS, AIM-120, ALR-56M, ALQ-184, ALE-50, HTS-P, SY0730 software-load IDs, "PRIOR SORTIES" line). The replacement is a filename/title alignment fix, not a re-redaction. Finds entry updated to document the refutation explicitly as editorial discipline. State memo replacement OCR'd to reveal a 1952 Samford-to-Nitze flying-saucer briefing memo — genuinely interesting historical content; finds entry expanded with citations.
- **Two API key leaks (mine, not the operator's)** during shell-expansion mishaps earlier in the session — ANTHROPIC_API_KEY + VOYAGE_API_KEY + PURSUE_CF_API_TOKEN all rotated by the operator. Verified-safe `[ -n "$VAR" ]` bracket pattern is now the only env-existence check pattern used.

**2026-05-12 (overnight) — Archive integrity stack shipped + /gallery complete + repo cleanup.**

- **CSV byte preservation + 30-min cadence (`a88fd18`).** Every poll now writes `data/raw/csv/<sha>.csv` content-addressed, idempotent. Bumped cron `0 */6 * *` → `*/30 * * * *`. Closes the f07601eb-tranche-lost gap. 22 poll tests + 3 new TDD tests for byte-archive contract pass.
- **R2 content-addressed asset archive (`7cd9708`).** `scripts/r2_archive_assets.py` runs on detected CSV change. HEAD-then-GET pre-flight skips unchanged assets cheaply; uploads to `archive/<byte_sha256>.<ext>` (append-only, never overwrites) AND `<card_id>.<ext>` (current pointer, what worker/pdf.js serves). Defeats the same-URL-different-bytes overlay attack.
- **Daily byte-verify cron (`9bd924d`).** `.github/workflows/verify-assets-daily.yml` — 06:00 UTC, same script, catches silent same-URL-different-bytes swaps the CSV poll cannot. Auto-opens `silent-overlay-detected` issue with dedup guard if any new row lands.
- **R2 archive baselined (`3edb5d3`).** First full pass tonight: 129/129 eligible cards have a registry row. 0 failures. The daily verify cron now has a real baseline to diff against.
- **/removed surface (`ef00c85`) + 3 finds writeups (`2970f56`).** First captured upstream removal event: FBI 62-HQ-83894 Section 6 (PDF link set to "N/A" upstream), the NASC-State 1963 file-swap (a different 1952 file now lives at that title pattern), and DOW-UAP-D20 (replaced with new card at same title, different filename). All three preserved in our archive. Hanawalt cobalt-ray finds entry also shipped (`4057a29`).
- **/gallery Phase 1 + 2 (`4c92367`, `d622431`, `17b847e`).** Image + video tile browse with type filters and year buckets. Video tiles use real poster frames extracted from operator-downloaded DVIDS .mp4s (25 of 28 unique card_ids; remaining 3 are card_id collisions from PR-series videos sharing parent MISREPs). PDF tiles use page-1 WebP thumbnails (115 of 116; one card has upstream `asset_url: N/A`). ~3.1 MB total static assets, well under CF Workers Static Assets ceilings.
- **Two Codex P2 fixes (`f94a00b`).** Issues #38 (`build_pages_cleaned.py` missing-page → skip+log) and #39 (`select_pilot_cards.py` backfill round-robin). Closed.
- **Methodology disclosure (`a0d3af3`).** Full-corpus skip rate (0.55%, 23 of 4153 pages), per-skip-reason breakdown, interpretive-cleanup boundary made explicit (1.48 → 1.4a allowed; redaction fill-in never).
- **Incident-date audit (`2b9964d`).** Systematic findings for issue #36 at `data/incident-date-audit.md`. Scraper not at fault — upstream CSV is the source. Editorial rule: prefer in-body MISREP DTG over manifest `incident_date` for /finds entries. Per-card OCR-pass follow-ups for D27 + 6 N/A cards remain.
- **Plug-the-leak hygiene.** After two accidental secret leaks (rotated both API keys + CF API token), all env existence checks now use the `[ -n "$VAR" ]` bracket pattern. Verified safe.

Tonight's commit run on `main`: 24 commits from `0035f3f` (pre-overnight) to current HEAD. All deploys live or propagating.

**2026-05-11 (evening) — Regression bug hunt + tranche f07601eb ingest + integrity ask landed.**

- **PDF iframe sandbox regression fixed (#48 — direct to main, `4e03a1d`).** Chrome 147 PDFium changed behavior: any `<iframe sandbox=...>` now suppresses inline PDF rendering regardless of allow-* tokens. Every card detail page on desktop Chrome was shipping a blank iframe; mobile masked it (system PDF viewers). Trust basis for dropping sandbox: post-PR #27 the iframe loads only same-origin `/pdf/<card_id>.pdf` from our R2 mirror, not adversarial content. CSP `frame-ancestors 'self'` + `X-Frame-Options: SAMEORIGIN` + worker card_id regex validation provide defense-in-depth.
- **Security bundle (`b6dba3f`).** HSTS header `max-age=31536000; includeSubDomains` (preload deliberately omitted) + RFC 9116 `/.well-known/security.txt` per operator audit. Clears 3 of the 11 audit items; DMARC + Always-Use-HTTPS + AI-bot toggles are operator dashboard/DNS actions.
- **Reader/Cleaned pagination regression fixed in two passes (`6d41ac6` then `ed93bb0`).** Operator-reported "first click works, then stuck" across both Reader and Cleaned modes, desktop + mobile. Reproduced live: rapid clicks within a single tick batched correctly (state 1→5), but sequential clicks with any wait failed after the first. The first-pass useReducer fix did not clear it on prod. Second pass refactored to ref-driven `navigateTo(target)`: handlers read `activePageRef.current` + `totalRef.current` live, compute the explicit target page, dispatch a `set` action, and do `history.replaceState` + iframe sync inline in the same call. Eliminates the deferred-useEffect race that was the root cause.
- **Mobile title overflow fixed (`e0d7add`).** `break-words` on the card title h1 so long technical filenames wrap on narrow viewports.
- **Augment loader hardened (`d60d9d9`).** Four corrupt rows (lines 448–451) in `alex-zhang42-corpus.jsonl` were aborting the entire embed. Parser now skips per-row with a logged sample and a 5% wholesale-corruption guardrail.
- **Cleaned-mode fetch race fixed (`e5defd7`).** The pre-existing "sometimes loads, sometimes doesn't — refresh fixes it" hang: useEffect dep `cleanedStatus` caused the fetch effect to re-fire on every status transition (idle → loading → loaded), racing with the 7.7 MB `r.json()` parse and stranding state on "loading." Gated via `useRef` flag; deps shrink to `[mode, base]`; cleanup-cancellation on unmount/mode-switch.
- **Tranche f07601eb ingested.** Scrape → 158 cards (was 119; +39: 28 VIDs + 14 IMGs + 0 net new PDFs). Download → 129/158 (the 29 missing are DVID-hosted videos; `PURSUE_DOWNLOAD_VIDEOS` default off). OCR → 116 PDF cards (no new pages). Embed → 1216 new embeddings, 2911 skipped, 418,704 tokens, **~$0.025**. Then re-run with augment-from: 1132 pages got VLM image tags (lenient parser caught the 4 corrupt rows).
- **API key rotation.** Operator rotated `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY` after the assistant accidentally printed both via a misused `${VAR:-default}` bash expansion. New keys deployed to `.env` (local) and CF Worker secrets (live via `npx wrangler secret put`). No GitHub Actions reference either key.

**2026-05-11 — Fact-check pass + LLM-cleaned pilot resume.**

- A r/UFOs reader DM'd the operator pointing out that the Muroc-1947 entry stated Roswell was "2,000 miles east" of Muroc/Edwards AFB. Actual great-circle distance is ~800 mi. Fixed directly on `main` as `5c8a0a9`.
- Defensive fact-check pass across all 14 `/finds` entries (via Explore agent). Verified Apollo 17, Kenneth Arnold, LaPaz fireballs, Mantell, Rhodes Phoenix, FBI 62-HQ-83894 sectioning, LaPaz/Institute of Meteoritics. **No additional factual errors.**
- One HIGH-severity ambiguity surfaced and fixed: D23 entry's manifest `incident_date: 10/31/2023` vs MISREP Zulu DTGs (Oct 24, 2023). In-entry clarifier landed as `d7258e9`. Manifest-field correction continues as Issue #36.
- LLM-cleaned pilot resume kicked off: `pursue clean run --cards <30> --budget-usd 0.75`. PR #46's content-filter graceful-skip validated in production (page 93 of card `7d58f0cac741650a`). Pilot hit the cap at 3 cards; extension pilot on 3 modern MISREPs (D23/D32/D33) added at $0.08, zero skips. Combined pilot output: 385 cleaned pages + 88 skip rows across 6 cards for $0.83.
- Spot-check checklist for the pilot output landed at `.paircoder/plans/llm-cleaned-pilot-spotcheck.md` — 40 checks across 5 pages, ship-readiness criteria explicit. Manual spot-check executed; **0 hard signals + 1 soft signal across 5 pages → GO verdict**. Lone soft signal: D33 p1 `1.48 → 1.4a` interpretive cleanup (single-character OCR fix in context, defensible but worth documenting in methodology).
- Full corpus pass launched: `pursue clean run --budget-usd 25.00`. Running in background; projected $8–12 spend across ~4,153 pages.
- QC engine plan landed: `.paircoder/plans/clean-quality-review.md` — LLM-judge layer over the cleanup output, ~$6 (Haiku judge) or ~$42 (Sonnet judge) per corpus pass, with explicit calibration discipline (20-page operator sample per run).

**2026-05-10 — v1.0.0 shipping run (19 PRs merged).**

- v1.0.0 tag + GitHub release shipped against PURSUE Release 01.
- 14 finds entries live (was 11): added D32 (#32), D23 (#34), D33 (#35).
- LLM-cleaned reading text overlay shipped as **dark code** (#37): pipeline + CLI + UI toggle live, `pages-cleaned.json` not yet produced. Toggle reads "Cleaned text not yet available for this card." Full corpus run is the gate to flip live (pilot in progress, see above).
- Content-filter graceful-skip (#46): runner no longer crashes on Anthropic moderation rejections; writes a `content_filter` skip row and continues.
- Self-hosted PDFs via Cloudflare R2 (#27) — fixes war.gov framing-block iframe issue.
- Atlas regl-scatterplot fixes (#25, #26, #30, #31): CSP unsafe-eval, UMAP [-1,1] normalization, colorBy/opacityBy lookup-array config, mobile cluster fallback retired.
- Search title-match highlight + dropped fuzzy expansion (#29).
- alex-zhang42 augmented retrieval elevated to project differentiator (#41); `/methodology` deep-links to OCR benchmark (#42).
- Repo audit cleanup: redactions + housekeeping (#44), accessibility audit + remediation plan (#45), pursue-vision-augment Phase 2 plan (#43), CI tightening (#22, #23, #24, #28), agent-memory untracked from public repo (#21 era).

## Known dark code

| Feature | Implementation | Wiring | Validation | Output | Live? |
|---|---|---|---|---|---|

No dark code currently. The LLM-cleaned reading text shipped fully on 2026-05-11 (PR #37 + #46 + `0035f3f` for the asset + post-deploy pagination/race fixes). The dark-code row from earlier in the day cleared with `0035f3f`; subsequent fixes were live-bug regression patches, not unwired features.

## Current Focus

Public site live at <https://pursueindex.com>. Full pipeline (scrape →
download → OCR → embed → serve) shipped end-to-end against PURSUE
Release 01. Chat interface live with mandatory `[card_id:page]`
citation discipline and abstention behavior. Repository is public
(`BPSAI/pursue-index`, Apache-2.0).

A complementary CC0 dataset (`alex-zhang42/ufo-pursue-open-atlas`)
released for the same source with VLM-described image content; we
credit it on `/methodology` under Related Work and ingest its
image-description blocks into our retrieval index.

## Active Plan

| Stage     | Status   | Output                                                             |
|-----------|----------|--------------------------------------------------------------------|
| scrape    | shipped  | curl_cffi + Chrome TLS, 161-card manifest, hash-pinned             |
| download  | shipped  | 116 PDFs + 14 images on NAS via content-addressable layout         |
| ocr       | shipped  | 3,529 Surya pages + 624 LLM-cleaned pages (auto-mode), 4,153 total |
| embed     | shipped  | Voyage-3 1024d float16, ~8 MB in-browser payload (1,208 augmented) |
| serve     | shipped  | Astro static + CF Worker (CORS-locked, 5/IP/24h, $100/day cap)     |
| chat      | shipped  | RAG with mandatory citations, anonymous + BYOK tiers               |
| novelty   | shipped  | machinery + UI; placeholder reference corpus (10 passages)         |
| atlas     | shipped  | 2D UMAP semantic browser at `/atlas` (4,119 dots, regl-scatterplot) |

## What's Live

- Custom domain at `pursueindex.com` on Cloudflare Workers + Static Assets.
- Full-text + semantic search across 4,153 OCR'd pages (MiniSearch lexical + Voyage-3 embeddings, both browser-side).
- OCR pipeline: Surya (GPU, transformer-based) primary + Anthropic vision LLM fallback for low-confidence pages.
- RAG chat with mandatory citations: anonymous tier (server-funded, 5/IP/24h, $100/day budget cap) and BYOK tier (browser-direct to Anthropic).
- Faceted search filters on `/search` (agency, incident date, redacted-only).
- Per-entry OG image cards for `/finds/<slug>` social sharing.
- Reader-mode toggle on card detail pages with `j`/`k` page navigation; iframed PDF stays in sync via `#page=N` deep linking.
- `/atlas` semantic browser: clickable UMAP projection of all 4,119 page embeddings, MiniSearch-backed search highlight, mobile cluster-list fallback.
- Public API documentation at `/api`.
- Auto-poll for new tranches: GitHub Actions cron every 6 hours fetches the upstream CSV, hashes it, opens an issue on change or fetch failure.
- Tranche diff page surfaces per-card deltas when the upstream CSV changes.
- Curated `/finds` reading guides (14 entries; added D32, D23, D33 in the 2026-05-10 run).
- Novelty detection scaffold with a synthetic placeholder reference corpus (10 passages); Black Vault integration on the backlog.
- PDF hosting self-managed from Cloudflare R2 (was war.gov direct iframe; broken by upstream framing-block mid-build).
- alex-zhang42 CC0 augmented-retrieval dataset surfaced as project differentiator on `/methodology` and in `/api/retrieve` responses (1,208 augmented chunks in the embedding index).

## Build and Deploy

- **Primary:** Cloudflare Workers Builds, configured via the dashboard. Triggers on push to `main`. Build: `cd web && npm install && npm run build`. Deploy: `npx wrangler deploy`.
- **Manual fallback:** `.github/workflows/deploy-cf.yml` runs the same chain via GitHub Actions on `workflow_dispatch`. Available as a button if Workers Builds stalls.
- **Local:** `npx wrangler deploy` from a clean checkout. Requires `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in env (or `wrangler login`).

## What's Next

### Active

_Nothing currently in flight. Tranche 65572b38 fully approved and ingested-promoted; card-rename plan complete (steps 1-7 + 1 historical alias). Section 6 finds entry could optionally be updated with a "restored 2026-05-12 — byte-verified" section (small editorial follow-up, parallel to the NASC-State pattern from this morning)._

### Recommended next priorities

**1. Documentation staleness remediation (HIGHEST RECOMMENDED).** Already-scoped: 31 specific findings catalogued in `pursue-opsec/findings/2026-05-12-documentation-staleness-audit.md`. Three drift classes: tool/engine names (Tesseract→Surya hedges), numeric facts (page counts, embed counts, etc. — surgical fixes done tonight on `index.astro`+`atlas.astro`+`README.md`+`docs/architecture.md`, but most surfaces remain), and architectural claims that haven't caught up to the integrity stack + /gallery + /removed work shipped in v1.1.0. Low-risk (no API budget, no infrastructure changes), high editorial-credibility return, scoped work. Operator-attended ~2-3 hours or one focused agent dispatch + operator review of the patch set.

**2. Accessibility audit + remediation.** Plan: `.paircoder/plans/accessibility-audit-and-remediation.md`. Priority HIGH per the plan; civic responsibility for a public archive. Includes the regl-scatterplot a11y challenges on `/atlas`. No deps.

**3. Black Vault reference corpus.** Plan: `.paircoder/plans/black-vault-reference.md`. Replaces the placeholder synthetic novelty corpus (10 hand-crafted passages) with a real FOIA prior-disclosure archive. Makes the novelty detection feature meaningful rather than illustrative. Medium priority; depends on existing novelty-detection scaffold (already shipped).

### Other backlog (in current order)

- **`pursue-vision-augment` Phase 2** — our own VLM pass alongside alex-zhang42 augmented retrieval, with per-page provenance distinguishing the two sources. Plan: `.paircoder/plans/pursue-vision-augment.md`.
- **Curated finds expansion** — 17 entries now set the editorial bar (3 new today: 1947 Wyly teletype, 2025 USPER orb, Apollo 11 debriefing); corpus has more strong candidates. Plan: `.paircoder/plans/curated-finds.md`.
- **`clean-quality-review`** — LLM-judge layer over cleanup output. Pilots when capacity opens up. Plan: `.paircoder/plans/clean-quality-review.md`.
- **Incidents map clustering** — geographic density visualization. Plan: `.paircoder/plans/incidents-map-clustering.md`.
- **Display-date curation** — UI improvement. Plan: `.paircoder/plans/display-date-curation.md`.
- **Review-and-correct pipeline** — accept community OCR transcript corrections via GitHub issues. Plan: `.paircoder/plans/review-correct.md`.
- **Autonomous finds pipeline** — auto-draft finds entries from new tranches, operator-gated for editorial publish. Plan: `.paircoder/plans/autonomous-finds-pipeline.md`.

### Open issues

- **#36** — Manifest `incident_date` audit across modern D## entries. Low priority.
- **#56** — Tranche 65572b38 detected (auto-filed by poll). **Resolved by tonight's ingest run; can be closed.**

### pursue-opsec follow-ups

- **pursue-opsec#1** — RFC: tier-2 cryptographic signing of registry rows. Awaiting operator decision on key-handling option (4 options laid out).
7. **Autonomous finds pipeline.** Background drafting of finds entries from new tranches, operator-gated for editorial publish. Plan: `.paircoder/plans/autonomous-finds-pipeline.md`.

### Open issues

- **#36** — Manifest `incident_date` audit across modern D## entries. In-entry clarifier for D23 landed 2026-05-11 (`d7258e9`); manifest-field correction still pending. Priority: Low.

## Reproducibility

The corpus pipeline is fully scripted and idempotent. From a clean
clone with the upstream CSV available:

```bash
pursue scrape run                                        # writes manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json
```

Each stage is content-addressed by `card_id = sha256(asset_url || title)[:16]`,
so partial reruns converge on the same final state regardless of order.
The manifest carries `csv_sha256` so upstream changes are detectable
in O(bytes-of-CSV).

## Quick Commands

```bash
# Pipeline (idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json --augment-from data/external/alex-zhang42-corpus.jsonl

# Tests
pytest -x                      # python
npm --prefix worker test       # worker
cd web && npm run build        # web (~169 pages)

# Web dev
cd web && npm run dev          # localhost:4321

# Worker dev (against real KV + secrets)
npx wrangler dev
```

## Blockers

None.
