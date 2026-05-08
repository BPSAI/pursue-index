#!/usr/bin/env bash
#
# Cloudflare inventory for pursueindex.{com,ai}.
# Reads PURSUE_CF_API_TOKEN, PURSUE_CF_ACCOUNT_ID from .env and prints a
# compact status report: token validity, zones, DNS records, Pages
# projects, page rules.
#
# Usage:
#   scripts/cf_status.sh
#
# Requires: curl, python3, jq is NOT required (we use python3 inline).
# Token scopes used: User Tokens (token verify), Zone:Read, Zone DNS:Read,
# Page Rules:Read, Account Cloudflare Pages:Read. Add Zone Settings:Read
# to expand the SSL/TLS section.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: .env not found at $ENV_FILE" >&2
  exit 1
fi

# Source .env without leaking values to subprocess args.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if [[ -z "${PURSUE_CF_API_TOKEN:-}" || -z "${PURSUE_CF_ACCOUNT_ID:-}" ]]; then
  echo "error: PURSUE_CF_API_TOKEN and PURSUE_CF_ACCOUNT_ID must be set in .env" >&2
  exit 1
fi

API="https://api.cloudflare.com/client/v4"

cf_get() {
  curl -s -H "Authorization: Bearer $PURSUE_CF_API_TOKEN" "$API$1"
}

py() { python3 -c "$1"; }

echo "=== token ==="
cf_get "/user/tokens/verify" | py 'import json,sys;d=json.load(sys.stdin);print("valid:",d["success"],"status:",d["result"].get("status") if d["success"] else d.get("errors"))'

echo
echo "=== zones in account ==="
cf_get "/zones?account.id=$PURSUE_CF_ACCOUNT_ID&per_page=50" \
  | py 'import json,sys
d=json.load(sys.stdin)
if not d["success"]:
    print("error:", d.get("errors")); sys.exit(1)
for z in d["result"]:
    name = z["name"]; status = z["status"]; zid = z["id"]
    print(f"  {name:25} status={status:10} id={zid}")'

echo
echo "=== DNS per pursueindex zone ==="
for ZONE_NAME in pursueindex.com pursueindex.ai; do
  ZID=$(cf_get "/zones?name=$ZONE_NAME" | py 'import json,sys;d=json.load(sys.stdin); print(d["result"][0]["id"]) if d.get("result") else print("")')
  if [[ -z "$ZID" ]]; then
    echo "  $ZONE_NAME: not in account"; continue
  fi
  echo "  --- $ZONE_NAME ($ZID) ---"
  cf_get "/zones/$ZID/dns_records?per_page=100" | py '
import json,sys
d=json.load(sys.stdin)
if not d["success"]:
    print("    error:", d.get("errors")); sys.exit()
for r in d["result"]:
    proxied = "proxied" if r.get("proxied") else "dns-only"
    val = str(r.get("content",""))[:60]
    rtype = r["type"]; rname = r["name"]
    print(f"    {rtype:6} {rname:30} -> {val:60} {proxied}")'
done

echo
echo "=== page rules per zone ==="
for ZONE_NAME in pursueindex.com pursueindex.ai; do
  ZID=$(cf_get "/zones?name=$ZONE_NAME" | py 'import json,sys;d=json.load(sys.stdin); print(d["result"][0]["id"]) if d.get("result") else print("")')
  [[ -z "$ZID" ]] && continue
  COUNT=$(cf_get "/zones/$ZID/pagerules" | py 'import json,sys;d=json.load(sys.stdin); print(len(d.get("result",[])))')
  echo "  $ZONE_NAME: $COUNT page rule(s)"
done

echo
echo "=== Cloudflare Pages projects ==="
cf_get "/accounts/$PURSUE_CF_ACCOUNT_ID/pages/projects" | py '
import json,sys
d=json.load(sys.stdin)
if not d["success"]:
    print("  error:", d.get("errors")); sys.exit()
if not d["result"]:
    print("  (none — connect a project via CF dashboard)")
for p in d["result"]:
    domains = p.get("domains") or []
    name = p["name"]; subdomain = p.get("subdomain","")
    print(f"  {name:25} subdomain={subdomain:40} domains={domains}")'

echo
echo "=== bulk redirect lists (account-level) ==="
cf_get "/accounts/$PURSUE_CF_ACCOUNT_ID/rules/lists" | py '
import json,sys
d=json.load(sys.stdin)
if not d["success"]:
    print("  error:", d.get("errors")); sys.exit()
redirects = [x for x in d.get("result",[]) if x.get("kind") == "redirect"]
if not redirects:
    print("  (no redirect lists yet — needed for pursueindex.ai → .com 301)")
for x in redirects:
    name = x["name"]; items = x.get("num_items",0); kind = x["kind"]
    print(f"  {name:25} items={items} kind={kind}")'
