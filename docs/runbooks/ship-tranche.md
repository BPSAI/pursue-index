---
description: Drive a detected war.gov tranche through the operated release, deterministically
argument-hint: [<csv_sha256>]  (omit to use the newest open tranche-detected issue)
---

# Ship Tranche

The turnkey document-release driver. Runs the dialed-in sequence with a hard
**verify-before-spend** engine gate so the Release-4 fumble (stale env →
tesseract-primary, download-concurrency 4 mistaken for OCR, skipped curate,
stale model) cannot recur. Two human gates only: **approval** and **deploy**.

## Input
$ARGUMENTS

## Preconditions
- Run from `pursue-index/` on a release branch. Do NOT load credentials yet:
  the operator's credential file is sourced only after HUMAN GATE #1 (step 3).
  Details of that file live in the private ops runbook.
- The operated config is non-negotiable: OCR `--engine llm-dots` (Sonnet 4.6, dots
  content-filter backstop) at `--concurrency 8`. tesseract/surya/auto are retired.
- Each spending stage runs in its own memory scope (no budget carryover between stages).

## Workflow

1. **Resolve the tranche.** If `$ARGUMENTS` is a sha, use it. Else take the newest
   open issue carrying the `tranche-detected` label that was filed by the poll bot:
   `gh issue list --state open --label tranche-detected --author "app/github-actions" --limit 1 --json number,title,body`.
   Never select by free-text title search (the repo is public; anyone can file a
   look-alike issue). Extract the sha and set `SHA` from it, then validate
   IMMEDIATELY, before any other use:
   ```
   printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{64}$' || { echo "bad SHA"; exit 1; }
   ```
   `SHA` must match `^[0-9a-f]{64}$`. On mismatch, STOP — do not run any later step.
   Every later expansion of `SHA` is double-quoted.
2. **Load the already-computed diff (no recompute).** Read the diff from
   `data/tranche-diffs/tranche-diff-"${SHA:0:12}".md` (+ the `.json`) and the poll
   verdict. The poll's snapshot job commits that receipt, with the byte verdicts,
   alongside the machine-readable record `data/tranche-ready/"${SHA:0:12}".json`. Inspect the worklist header to confirm CSV SHA and source URL (byte-provenance).
   Summarize: verdict, added/removed/field-only/new-columns, the scoped
   work-list, and the `~$` estimate. Do NOT re-fetch bytes.
3. **HUMAN GATE #1 — approval.** Present the summary. Get explicit "yes". Then:
   `pursue ingest approve --tranche "$SHA" --note "<operator note>"` (runs the TOCTOU re-audit).
   Only now load the operator's credential file (the private operations checkout
   holds it; see the private ops runbook): `set -a; source "$OPERATOR_ENV_FILE"; set +a`.
4. **VERIFY-BEFORE-SPEND (the guard).** Before any OCR, confirm the operated
   methodology + the 3-tier storage contract, or REFUSE:
   ```
   pursue storage verify   # NAS + main R2 (pursue-pdfs) + backup R2 (pursue-pdfs-backup) all configured
   pursue ingest run --tranche "$SHA" --from-diff --dry-run   # scope + WRITES data/ingest-worklist.txt, no spend
   python scripts/ship_preflight_ocr.py --engine llm-dots --concurrency 8   # same values as step 6; key present
   ```
   If the preflight fails (engine not llm-dots/llm, concurrency < 8, or no key), STOP and fix — do not spend.
   `pursue storage verify` exits non-zero if any tier is unconfigured; read its
   WARNING lines; backup-tier caveats are documented in the private ops runbook.
   The `--from-diff --dry-run` step MATERIALIZES `data/ingest-worklist.txt` for
   the detected tranche (credential-free, no spend) so the OCR step below runs on
   the RIGHT card set — do not skip it (Codex #101 P1).
5. **Promote:** `pursue ingest run --tranche "$SHA"` (deterministic, no spend). Does
   NOT rewrite the worklist — step 4's dry-run already wrote it for this tranche.
   It also does **not** download: it prints the remaining pipeline and exits.
5b. **Download the bytes** (deterministic, no LLM spend — a separate stage, easy to
   miss because step 5 looks like it ingested):
   ```
   pursue download run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt
   ```
   Confirm `download.summary downloaded=N total=N` with N = the scoped count.
   After download completes, build PDF thumbnails:
   ```
   python scripts/build_pdf_thumbs.py
   ```
5c. **A/V cards (auto-fetched bytes).** war.gov never publishes direct links
   for `VID`/`AUD`, so those cards land with `asset_url=None`. They will NOT
   appear in the worklist and are invisible to every step below — check for
   them explicitly, then fetch:
   ```
   pursue av-fetch run --manifest data/manifests/latest.json \
       --release-date "<M/D/YY>" --staging-dir <dir> --dry-run   # scope preview, no fetch
   pursue av-fetch run --manifest data/manifests/latest.json \
       --release-date "<M/D/YY>" --staging-dir <dir>             # the fetch; exits non-zero on any shortfall
   python scripts/ingest_release_videos.py --release-date "<M/D/YY>" \
       --desktop <dir> --env "$OPERATOR_ENV_FILE" \
       --source-label "war.gov/release_NN (DVIDS videos)" --dry-run
   ```
   `av-fetch run` resolves each card's DOD asset URL from its `/video/<id>`
   page (VID and AUD alike) and downloads directly — same
   Chrome-impersonation client as war.gov, no operator download step. Its
   `--staging-dir` output is exactly what `--desktop` already consumes,
   unchanged. If `av-fetch run` can't reach an asset (CDN block, transport
   error), it reports the card and exits non-zero — fall back to an operator
   download into the same `--staging-dir` for the missing card_ids only. The
   `ingest_release_videos.py --dry-run` maps cards→files by DOD asset id;
   require `matched = N / 0 cards-without-file / 0 files-without-card` before
   the real run (drop `--dry-run`). Stages to NAS + R2 (`archive/<sha>.mp4` +
   `<card_id>.mp4` pointer) and appends a registry row. Then
   `scripts/build_video_posters.py`.
5d. **Transcribe audio (A/V cards with audio):**
    After A/V fetch, run the verify-before-spend coverage check for the tranche:
    ```
    pursue transcribe run --manifest data/manifests/latest.json --release-date <tranche release date>
    ```
    This is a preflight only: it lists eligible AUD rows against produced transcripts,
    makes no AssemblyAI call, and exits non-zero on a coverage shortfall. The bulk
    transcription pass is operator-attended (see the private ops runbook); use
    `--live-smoke <card_id>` to smoke-test a single card. Transcript sidecars land
    under the OCR data root next to each card's other sidecars.
6. **OCR (the spend):** `pursue ocr run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt --engine llm-dots --concurrency 8 --force`.
   **Read the first log lines and confirm `engine=llm-dots` / `model=claude-sonnet-4-6` — kill immediately on `auto`/`tesseract`.**
   Note `ocr.start_all` reports `pdf_cards=N` — N counts **PDF cards only**.
   `IMG` cards are not OCR'd here; they are covered by the vision path at embed.
   Each spending stage runs in its own memory scope; do not reuse the same process.
7. **PDF r2-mirror + verify (after OCR):** the curate clean-qc judge
   renders page images from the NAS-local `r2-mirror/archive/<pdf_sha256>.pdf`.
   A normal ingest uploads PDFs to R2 but does NOT stage that local copy (the
   Release-4 gap → silent `missing_page_image`). Stage them, then gate:
   ```
   pursue storage mirror-pdfs  --worklist data/ingest-worklist.txt   # idempotent, sha-verified copy
   pursue storage verify-mirror --worklist data/ingest-worklist.txt  # fail-fast; exits non-zero if any missing
   ```
   `mirror-pdfs` is a no-op for already-mirrored cards. If `verify-mirror`
   fails, STOP — do not run clean-qc until every in-scope PDF card resolves its
   `r2-mirror/archive/<sha>.pdf`, or the judge produces silent misses.
   Both commands print a `[scope] …` line when the worklist contains non-PDF
   cards (`IMG`/`VID`/`AUD` have no PDF and are excluded by design). Scoping
   fails closed — an unknown card or one with no `asset_type` stays gated. If
   the skipped count is anything other than the tranche's non-PDF cards, STOP.
8. **Vision preflight (after OCR):** IMG-card assets and genuinely image-only PDF pages (zero base OCR)
   carry no searchable text until our own vision pass describes them; embed
   reads those descriptions from `web/src/data/image-observations/<card_id>.json`.
   - **Verify-before-spend preflight (no API calls):**
     ```
     pursue vision run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt
     ```
     Prints `vision coverage: P produced / E eligible` and **exits non-zero on
     any shortfall** (eligible items with no sidecar). This is safe in CI and
     for anyone — it never spends. Run it first; the missing list is the exact
     backfill worklist.
   - **The spend is operator-attended, single-card at a time.** `--live-smoke
     <card_id>` is the ONLY live path: it examines one card via the pinned
     vision model (`claude-opus-4-8`, a code constant) and writes its sidecar —
     the single-image smoke that proves the generator before any bulk run. CI
     **never** passes `--live-smoke`. The bulk backfill of the uncovered IMG
     cards + image-only pages is a deliberate operator-attended run, not wired
     into `ship-tranche`'s automated path.
   - Re-run the preflight after backfilling; it must reach `produced ⊇ eligible`
     (exit 0) before embed, or those image-only pages embed with no text.
9. **Clean, then QC — two stages, both required.**
   a. **Clean (pursue-index, Haiku):** clean-qc consumes `pages_cleaned.jsonl`,
      which OCR does not produce. Skip this and clean-qc aborts with a
      *`pages_cleaned.jsonl` not found … PURSUE_DATA_ROOT points at the wrong
      mount* error, which misdescribes the cause.
      ```
      pursue clean run --manifest data/manifests/latest.json --cards <PDF card ids> --budget-usd 8.0
      ```
      **The default `--budget-usd` is `8.0`,** the per-tranche spend ceiling.
      Pass PDF card ids only.
   b. **QC (pursue-curate, Sonnet vision judge):** Run and publish must be chained
      so publish never follows a failed run:
      ```
      curate clean-qc run --cards <PDF card ids> && curate publish clean-qc --version <N>
      ```
      **`--judge-all` is the default:** judge every page, not rules-first.
      To opt out and run rules-first only, pass `--rules-first`.
      An 81-page sample proved **51% of pages carry real issues the rules
      tier does not catch**. Sanity check against a prior release: sidecar rows
      should be ~100% judged with a `judge-ok` / `operator-review` mix,
      never 100% `no-corrections`. Budget ≈ $0.024/page.
      After `curate publish` completes, copy the bundle to the web checkout:
      ```
      make bundle-copy
      ```
      This stages the clean-QC bundle to `web/public/data/clean-qc-bundle.json`
      for the release build.
10. **Embed:** `pursue embed run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt` (voyage-3, re-embeds changed pages).
11. **GEO discovery refresh (LS1.4):** `python scripts/build_llms_txt.py` — regenerates
    the `## Cards` sections + provenance line of `web/public/llms.txt` and
    `llms-full.txt` from the promoted manifest. Must run BEFORE `make ship-ready`:
    these live in `web/public/`, so the build copies whatever is on disk. Verify
    with `python scripts/build_llms_txt.py --check` (release-gate step 4b runs the
    same check, so skipping this reds the PR).
12. **Ship-ready gate:** `make ship-ready`. Confirm astro built (~pages) and `cd web && npm run test` all-green. (Note: `make test` runs pytest under the .venv only if activated — validate the web tests explicitly.)
    `rebuild-derivatives` (inside ship-ready) now rebuilds the DERIVED SITE
    PAYLOADS per tranche — embed index, video posters, atlas layout (atlas
    last; it needs the `.[build-tools]` extra installed in the venv or it
    fails loudly, which is correct). Read each builder's coverage line: the
    embed index must contain every embed-eligible card of the tranche
    (eligibility = at least one page with non-empty text), poster coverage
    must equal the manifest's distinct A/V card count, and a poster
    regenerates automatically when a card's registry byte sha changed. The
    coverage gate test enforces this in CI; a red there means a payload
    would ship stale — never bypass it.
13. **HUMAN GATE #2 — deploy.** Show the diff + build/test results. On "yes":
    commit on the tranche branch, create a PR to `main`, then merge the PR to deploy.
    (Native CF Workers Builds fire on merge; do NOT use `git push origin main`.)
    After merge, auto-fires close-tranche, registry-root, post-deploy-verify, indexnow.
    Then purge/confirm the live card count (edge cache may lag).
14. **Finds + tag:** fan out finds reviewers over the new cards → publish quote-verified,
    cross-linked `/finds` (astro build re-validates every `<Cite>`), then
    `git tag vX.Y.Z && gh release create vX.Y.Z --latest` (both — a tag alone is not the release).
15. **Record:** update the private operations checkout's session record + write the finds digest (see the private ops runbook).

## Gates (MANDATORY)
- **Approval** (step 3) and **deploy** (step 13) require explicit human "yes" — these are the spend and the outward-facing, hard-to-reverse actions.
- **Never** move the OCR/embed spend or CF deploy into CI — the poll workflow's credential isolation is load-bearing.
- **Never** use `git push origin main` directly — create a PR and merge it (CF Workers Builds fire on merge).
- If running headless with no human to approve, STOP after step 4 and report.
