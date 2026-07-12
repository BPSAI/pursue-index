---
description: Drive a detected war.gov tranche through the operated release, deterministically
allowed-tools: Bash(*), Read, Edit
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
- Run from `pursue-index/`. First: `set -a; source ../pursue-opsec-staging/.env; set +a`
  (dangling `pursue-index/.env` symlink — always source opsec/.env explicitly).
- The operated config is non-negotiable: OCR `--engine llm-dots` (Sonnet 4.6, dots
  content-filter backstop) at `--concurrency 8`. tesseract/surya/auto are retired.

## Workflow

1. **Resolve the tranche.** If `$ARGUMENTS` is a sha, use it. Else take the newest
   open `tranche-detected` issue: `gh issue list --state open --search "tranche detected" --json number,title`.
   Set `SHA=<csv_sha256>`.
2. **Load the already-computed diff (no recompute).** Read
   `.paircoder/plans/tranche-diff-${SHA:0:12}.md` (+ the `.json`) and the poll
   verdict. Summarize: verdict, added/removed/field-only/new-columns, the scoped
   work-list, and the `~$` estimate. Do NOT re-fetch bytes.
3. **HUMAN GATE #1 — approval.** Present the summary. Get explicit "yes". Then:
   `pursue ingest approve --tranche $SHA --note "<operator note>"` (runs the TOCTOU re-audit).
4. **VERIFY-BEFORE-SPEND (the guard).** Before any OCR, confirm the operated
   methodology + the 3-tier storage contract, or REFUSE:
   ```
   pursue storage verify   # NAS + main R2 (pursue-pdfs) + backup R2 (pursue-pdfs-backup) all configured
   pursue ingest run --tranche $SHA --from-diff --dry-run   # scope + WRITES data/ingest-worklist.txt, no spend
   python -c "import os; from pursue_index.release.ship import preflight_ocr; \
     r=preflight_ocr(engine='llm-dots', concurrency=8, anthropic_key_present=bool(os.environ.get('ANTHROPIC_API_KEY'))); \
     print(r); import sys; sys.exit(0 if r.ok else 1)"
   ```
   If the preflight fails (engine not llm-dots/llm, concurrency < 8, or no key), STOP and fix — do not spend.
   `pursue storage verify` exits non-zero if any tier is unconfigured; note its
   same-account-backup WARNING (backup R2 shares the primary CF account today —
   not true DR; see `../pursue-opsec-staging/findings/2026-07-12-same-account-r2-backup.md`).
   The `--from-diff --dry-run` step MATERIALIZES `data/ingest-worklist.txt` for
   the detected tranche (credential-free, no spend) so the OCR step below runs on
   the RIGHT card set — do not skip it (Codex #101 P1).
5. **Promote:** `pursue ingest run --tranche $SHA` (deterministic, no spend). Does
   NOT rewrite the worklist — step 4's dry-run already wrote it for this tranche.
6. **OCR (the spend):** `pursue ocr run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt --engine llm-dots --concurrency 8 --force`.
   **Read the first log lines and confirm `engine=llm-dots` / `model=claude-sonnet-4-6` — kill immediately on `auto`/`tesseract`.**
7. **curate QC:** in `../pursue-curate`, `curate clean-qc run --cards <worklist ids>` then `curate publish clean-qc --version <N>` (reads OCR off the shared `PURSUE_DATA_ROOT` NAS). QC/methodology bundle — this is a real operated stage, not optional.
8. **Embed:** `pursue embed run --manifest data/manifests/latest.json --worklist data/ingest-worklist.txt` (voyage-3, re-embeds changed pages).
9. **Ship-ready gate:** `make ship-ready`. Confirm astro built (~pages) and `cd web && npm run test` = 18/0. (Note: `make test` runs pytest under the .venv only if activated — validate the web tests explicitly.)
10. **HUMAN GATE #2 — deploy.** Show the diff + build/test results. On "yes":
    commit + `git push origin main`. The push IS the deploy (native CF Workers
    Builds) and auto-fires close-tranche, registry-root, post-deploy-verify, indexnow.
    Then purge/confirm the live card count (edge cache may lag).
11. **Finds + tag:** fan out finds reviewers over the new cards → publish quote-verified,
    cross-linked `/finds` (astro build re-validates every `<Cite>`), then
    `git tag vX.Y.Z && gh release create vX.Y.Z --latest` (both — a tag alone is not the release).
12. **Record:** update `pursue-opsec-staging/.paircoder/context/state.md` + write the finds digest.

## Gates (MANDATORY)
- **Approval** (step 3) and **deploy** (step 10) require explicit human "yes" — these are the spend and the outward-facing, hard-to-reverse actions.
- **Never** move the OCR/embed spend or CF deploy into CI — the poll workflow's credential isolation is load-bearing.
- If running headless with no human to approve, STOP after step 4 and report.
