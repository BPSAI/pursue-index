# Current State

> Last updated: 2026-05-08

## Active Plan

**Plan:** Recover from CSV-pivot scrape regression
**Status:** Diagnosed — ready to apply header fix
**Current Sprint:** Bring v0.2.0 (CSV pivot) into a working state

## Current Focus

The `pursue-index-csv-pivot.tar.gz` patch landed cleanly (v0.1.0 → v0.2.0):
Playwright is gone, `csv_fetcher.py` + `normalize.py` replace
`extractor.py` + `playwright_runner.py`, manifests now live in
`PURSUE_MANIFESTS_DIR` (separated from NAS data root). 9/9 unit tests pass.

`pursue scrape run` fails at the live network step with `403 Forbidden` from
Akamai (`AkamaiGHost`). Diagnosis confirms the cause: the fetcher sends only
UA + Accept + Accept-Language + Referer. Akamai's bot rules require the full
Chrome client-hint header set (`Sec-Ch-Ua*`, `Sec-Fetch-*`, `Accept-Encoding`).
With those headers, the CSV downloads cleanly (185,105 bytes, 200 OK).

## Task Status

### Active Sprint

- [x] Apply CSV-pivot patch (extractor → csv_fetcher; manifests_dir split)
- [x] Diagnose 403 — Akamai bot detection, missing Chrome client-hint headers
- [ ] Stage + commit CSV-pivot diff (delete extractor/playwright_runner; add csv_fetcher/normalize; update env, settings, CLI, downloader, models, tests)
- [ ] Update local `.env` — drop `PURSUE_SOURCE_URL`/`PURSUE_SCRAPE_HEADLESS`/`PURSUE_SCRAPE_TIMEOUT_MS`, set `PURSUE_SCRAPE_USER_AGENT=` (empty so the realistic UA wins), add `PURSUE_CSV_URL`
- [ ] Patch `csv_fetcher.fetch_raw_csv` to send the full Chrome client-hint header set; add a regression test
- [ ] Run `pursue scrape run` end-to-end, archive raw CSV, write `data/manifests/latest.json`
- [ ] Push to `origin/main` (or feature branch if policy flips)

### Backlog

- OCR stage (`pursue ocr run`) — currently a stub
- Index stage (`pursue index ingest`) — currently a stub
- FastAPI search service (`pursue serve`) — currently a stub
- DVIDS video ingestion (off by default)

## What Was Just Done

### Session: 2026-05-08 — CSV pivot landed; 403 diagnosed

- Reviewed the patch produced by `pursue-index-csv-pivot.tar.gz`:
  - **Removed:** `src/pursue_index/scrape/extractor.py`,
    `src/pursue_index/scrape/playwright_runner.py`.
  - **Added:** `src/pursue_index/scrape/csv_fetcher.py`,
    `src/pursue_index/scrape/normalize.py`,
    `tests/unit/test_normalize.py`.
  - **Modified:** `.env.example`, `.gitignore`, `docs/architecture.md`,
    `pyproject.toml` (v0.1.0 → v0.2.0), `scripts/bootstrap_dev.sh`,
    `src/pursue_index/cli/commands.py`,
    `src/pursue_index/config/settings.py`,
    `src/pursue_index/download/downloader.py`,
    `src/pursue_index/index/models.py`,
    `src/pursue_index/scrape/__init__.py`,
    `src/pursue_index/scrape/types.py`, `tests/unit/test_manifest.py`.
- 9/9 unit tests pass under `pytest`.
- Reproduced the 403 with the current code path and confirmed Akamai accepts
  identical requests when sec-ch-ua / sec-fetch / accept-encoding are present.

## What's Next

1. Patch `csv_fetcher.fetch_raw_csv` to send Chrome-equivalent headers (TDD: failing test first).
2. Clean up `.env` to match the new contract.
3. Commit the patch + the header fix together.
4. Run `pursue scrape run` and verify the manifest lands.
5. Push.

## Blockers

None — the 403 is reproducible and the workaround is identified.

## Quick Commands

```bash
# Status
bpsai-pair status

# Tests
pytest -x

# Pipeline
pursue scrape run                                # writes data/manifests/latest.json
pursue download run --manifest data/manifests/latest.json
```
