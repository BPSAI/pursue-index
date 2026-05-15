---
name: release-pipeline-gate
description: Use when promoting a new tranche, modifying the manifest, or otherwise about to push changes that affect the deploy-side build. Runs the same deterministic checks as the release-gate CI workflow.
skills: [release-pipeline-gate]
agent-roles: [driver, nayru]
---

# Release Pipeline Gate

> Operator-local mirror of `.github/workflows/release-gate.yml`. Run
> this checklist before pushing changes that touch the manifest,
> snapshot mirrors, alias map, or finds entries. The CI workflow will
> re-run all of these in CI as the gate; running them locally first
> catches issues before the push round-trip.

## When to use

- Right after `pursue ingest run --tranche <sha>` promotes a new tranche
- After hand-editing `data/manifests/latest.json` or `data/card-aliases.json`
- After adding a new finds entry that uses `<Cite card="...">`
- Anytime you're about to commit a change to `data/manifests/snapshots/`
  or `web/public/data/snapshots/`

## What it catches

Deploy-side derived files going out of sync with the pipeline-side
source-of-truth. Concretely, the four classes of bugs that hit main
on 2026-05-12 in one evening:

| Bug class | Where it manifests | Caught by step |
|---|---|---|
| Pipeline + build manifest drift | Astro builds ship a stale manifest | 1 |
| Snapshot mirror lag | `/diff` page goes stale or references missing snapshot | 2-4 |
| Citation breakage | `/finds/<slug>` 404s when clicking a `<Cite>` | 5 |
| Missing card page | `/card/<id>` 404 from gallery / search | 6a |
| Dead alias destination | `/card/<old_id>` 301 → 404 | 6b |

## Steps

### 1. Sync the manifest mirrors

```bash
# If a new tranche is in play, promote it first:
pursue ingest run --tranche <sha>
```

This atomically refreshes:
- `data/manifests/latest.json` (pipeline source-of-truth)
- `web/src/data/manifest.json` (Astro build input)
- `web/public/data/snapshots/<sha>.json` + `index.json` (diff page)

### 2. Refresh operator-local derived assets (if applicable)

```bash
python scripts/build_video_posters.py   # idempotent; needs local .mp4s
python scripts/build_pdf_thumbs.py      # idempotent; needs local NAS PDFs
```

Both print a `no_local_*=N` summary and exit 0 when their inputs are
missing — safe to run unconditionally. CI runners don't have these
files, which is fine — CI relies on the previously-committed posters
and thumbs.

### 3. Build the site

```bash
cd web && npm run build
```

Catches Astro / TypeScript build errors before commit. Output lands
in `web/dist/`.

### 4. Run the gate test suite

```bash
pytest tests/unit/test_snapshot_mirror_coverage.py \
       tests/unit/test_finds_citations.py \
       tests/integration/test_card_page_coverage.py \
       tests/integration/test_alias_destinations.py \
       -v
```

All six AC enforced:

1. Pipeline `latest.json` byte-equal to build `manifest.json`
2. Pipeline + web snapshot dirs in sync (both directions)
3. Web `index.json` covers web filesystem
4. Paired snapshots byte-equal
5. Every `<Cite>` in `/finds` resolves via manifest or alias
6. Every manifest card_id has a `dist/card/<id>/index.html` (and every alias terminal does too)

### 5. Commit + push

```bash
git add data/ web/
git commit -m "<message>"
git push
```

The `release-gate.yml` workflow runs the same checks in CI on PR. If
you ran step 4 locally first, the CI run is a confirmation, not a
surprise.

## Quick one-liner for the local checklist

```bash
cd web && npm run build && cd .. && pytest \
  tests/unit/test_snapshot_mirror_coverage.py \
  tests/unit/test_finds_citations.py \
  tests/integration/test_card_page_coverage.py \
  tests/integration/test_alias_destinations.py
```

A green run here = a green CI run on push.

## When NOT to use

- Changes scoped entirely to worker code (`worker/*.js`) without
  touching `data/` or `web/src/data/` — the workflow won't trigger
  and these checks aren't load-bearing for that PR shape.
- Documentation-only PRs that don't touch the manifest.
- Hot-fixes that intentionally diverge (e.g. emergency manifest
  rollback) — in that case, the operator is the gate by definition;
  the workflow's job is to make sure that's a conscious choice, not
  an accident.
