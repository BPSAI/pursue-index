#!/usr/bin/env bash
# R2 PDF coverage smoke check: verify every PDF card in the manifest is
# actually reachable on the live `/pdf/<card_id>.pdf` route.
#
# Why this exists:
#   PR #27 (war.gov framing fix) self-hosts the corpus PDFs out of
#   Cloudflare R2 (`pursue-pdfs`, binding `PDFS`). The bulk-upload step
#   that copies ~116 PDFs into R2 is operator-driven, not CI-driven, so
#   nothing else catches the case where 5 cards in the manifest have no
#   corresponding object in the bucket — users would just see broken
#   iframes on those card pages. Run this after the bulk upload, before
#   merging the framing fix.
#
# What it checks:
#   1. Reads `data/manifests/latest.json` and extracts every `card_id`
#      whose `asset_type === "PDF"` (the only cards the iframe ever
#      tries to load).
#   2. For each card_id, issues `HEAD /pdf/<card_id>.pdf` against the
#      production host (or --base-url override) and checks for 200.
#      A 404 means the bulk upload missed that file.
#   3. Reports missing card_ids (manifest has it, R2 doesn't) and exits
#      non-zero so a human notices.
#
# Why HEAD instead of `wrangler r2 object list`:
#   Wrangler 4 dropped the `r2 object list` subcommand — the S3 LIST API
#   is the only programmatic way left, and that requires AWS creds for a
#   bucket that's normally accessed via the binding. HEAD against the
#   public route is the user-visible contract anyway: a card_id served
#   200 by the worker is reachable from the iframe, full stop.
#
# Orphan detection (objects in R2 not in manifest) is intentionally NOT
# attempted here because of the wrangler limitation above; if/when the
# operator needs that, run it from the Cloudflare R2 dashboard or via
# `aws s3 ls s3://pursue-pdfs --endpoint-url <r2-endpoint>` with creds.
#
# Usage:
#   scripts/smoke_r2_pdf_coverage.sh
#   scripts/smoke_r2_pdf_coverage.sh --base-url https://pursueindex.com
#   scripts/smoke_r2_pdf_coverage.sh --manifest data/manifests/latest.json
#   scripts/smoke_r2_pdf_coverage.sh --help

set -euo pipefail

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

BASE_URL="https://pursueindex.com"
MANIFEST="data/manifests/latest.json"

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    --manifest) MANIFEST="$2"; shift 2 ;;
    *) echo "unknown arg: $1 (try --help)" >&2; exit 2 ;;
  esac
done

if [ ! -f "$MANIFEST" ]; then
  echo "manifest not found: $MANIFEST" >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (apt-get install jq, or brew install jq)" >&2
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 2
fi

# Extract every card_id whose asset_type is PDF. The manifest contract
# (data/manifests/latest.json) ships these as 16-char lowercase hex.
PDF_IDS=$(jq -r '.cards[] | select(.asset_type == "PDF") | .card_id' "$MANIFEST")
TOTAL=$(printf '%s\n' "$PDF_IDS" | grep -c . || true)

if [ "$TOTAL" -eq 0 ]; then
  echo "no PDF cards in manifest; nothing to check" >&2
  exit 0
fi

echo "checking $TOTAL PDF cards against $BASE_URL/pdf/..."
MISSING=""
MISSING_COUNT=0
OK_COUNT=0

while IFS= read -r CARD_ID; do
  [ -z "$CARD_ID" ] && continue
  URL="$BASE_URL/pdf/${CARD_ID}.pdf"
  # -I = HEAD; -s silent; -o /dev/null discard body; -w prints status code.
  # Connection timeout 5s, total 10s — generous for a HEAD on Cloudflare.
  STATUS=$(curl -I -s -o /dev/null -w '%{http_code}' \
    --connect-timeout 5 --max-time 10 "$URL" || echo "000")
  if [ "$STATUS" = "200" ]; then
    OK_COUNT=$((OK_COUNT + 1))
  else
    MISSING="${MISSING}${CARD_ID} (HTTP $STATUS)"$'\n'
    MISSING_COUNT=$((MISSING_COUNT + 1))
  fi
done <<< "$PDF_IDS"

echo "ok: $OK_COUNT / $TOTAL"
if [ "$MISSING_COUNT" -gt 0 ]; then
  echo ""
  echo "MISSING ($MISSING_COUNT):"
  printf '%s' "$MISSING"
  exit 1
fi
echo "all PDF cards reachable on $BASE_URL"
