#!/usr/bin/env bash
#
# Integration smoke test for the /api/* dispatch contract.
#
# Why this exists:
#   PR #4 shipped the static /api docs page; PR #16 had to fix a regression
#   where the Worker's prefix-match `startsWith("/api/")` was shadowing the
#   docs page. Three reviewers missed the collision because the unit tests
#   in worker/tests/api_gate.test.js stub the ASSETS binding, and the web
#   test suite does not exercise the Worker. No test ran both halves
#   together. This script is that integration boundary test.
#
# What it asserts (the dispatch contract):
#   1. GET /api/         -> 200, HTML  (static docs page via ASSETS)
#   2. GET /api          -> 200, HTML  (bare path; trailingSlash: "ignore")
#   3. POST /api/retrieve with empty body -> 400, JSON "query required"
#   4. POST /api/chat    with empty body -> 400, JSON "query required"
#   5. GET /api/bogus    -> 404 from ASSETS (NOT the Worker's
#                          `{"error":"not found"}` JSON)
#   6. GET /api/changelog -> 404 from ASSETS (path has no static page and
#                          is not in WORKER_API_PATHS)
#
# Adding a new dynamic Worker route (WORKER_API_PATHS in worker/index.js)
# OR a new static /api/* page (web/src/pages/api*.astro) requires adding
# the corresponding assertion below so this contract test stays
# comprehensive.
#
# Usage (CI or local):
#   cd web && npm ci && npm run build && cd ..
#   bash scripts/smoke_api_dispatch.sh
#
# Exit codes:
#   0 - all six assertions passed
#   1 - any assertion failed, or wrangler dev did not come up in time
#
# Requirements: bash, curl, npx (with `wrangler` resolvable). The script
# does NOT require wrangler to be installed at the project root; npx
# fetches it on demand. CI is responsible for providing Node + npx.

set -u
set -o pipefail

# --- config ---------------------------------------------------------------

PORT="${SMOKE_PORT:-8788}"
HOST="http://127.0.0.1:${PORT}"
STARTUP_TIMEOUT_SECS="${SMOKE_STARTUP_TIMEOUT_SECS:-60}"
WRANGLER_LOG="$(mktemp -t wrangler-smoke-XXXXXX.log)"
PERSIST_DIR="$(mktemp -d -t wrangler-smoke-persist-XXXXXX)"

# Resolve repo root from this script's location so `bash scripts/...` and
# `bash ./scripts/...` both work regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PASSED=0
FAILED=0
WRANGLER_PID=""

log()  { printf '[smoke] %s\n' "$*"; }
fail() { printf '[smoke] FAIL: %s\n' "$*" >&2; }
ok()   { printf '[smoke] PASS: %s\n' "$*"; }

# --- teardown -------------------------------------------------------------

cleanup() {
  local exit_code=$?
  if [[ -n "${WRANGLER_PID}" ]] && kill -0 "${WRANGLER_PID}" 2>/dev/null; then
    log "stopping wrangler dev (pid ${WRANGLER_PID})"
    # Kill the whole process group; wrangler spawns a workerd child.
    kill -TERM -- "-${WRANGLER_PID}" 2>/dev/null || kill -TERM "${WRANGLER_PID}" 2>/dev/null || true
    # Give it a moment to drain, then SIGKILL if still alive.
    for _ in 1 2 3 4 5; do
      kill -0 "${WRANGLER_PID}" 2>/dev/null || break
      sleep 0.5
    done
    kill -KILL -- "-${WRANGLER_PID}" 2>/dev/null || kill -KILL "${WRANGLER_PID}" 2>/dev/null || true
  fi
  if [[ ${exit_code} -ne 0 ]]; then
    log "wrangler dev log (last 80 lines):"
    tail -n 80 "${WRANGLER_LOG}" >&2 || true
  fi
  rm -rf "${PERSIST_DIR}" 2>/dev/null || true
  rm -f  "${WRANGLER_LOG}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- preflight ------------------------------------------------------------

if [[ ! -d "${REPO_ROOT}/web/dist" ]]; then
  fail "web/dist not found. Run: (cd web && npm ci && npm run build) first."
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/web/dist/api/index.html" ]]; then
  fail "web/dist/api/index.html missing — the static /api docs page didn't build."
  exit 1
fi

# --- start wrangler dev ---------------------------------------------------

log "starting wrangler dev on port ${PORT} (log: ${WRANGLER_LOG})"
# `setsid` puts wrangler in its own process group so we can kill the
# whole tree (wrangler -> workerd) at teardown. --local + --persist-to
# /tmp keep it self-contained and avoid touching the operator's
# .wrangler cache.
(
  cd "${REPO_ROOT}"
  setsid npx --yes wrangler dev \
    --port "${PORT}" \
    --ip 127.0.0.1 \
    --local \
    --persist-to "${PERSIST_DIR}" \
    >"${WRANGLER_LOG}" 2>&1
) &
WRANGLER_PID=$!

# Poll /api/ until it returns 200 or we time out. We poll the docs page
# rather than `/` because /api/ is what the contract test cares about,
# and a 200 there means assets are wired AND the dispatcher is up.
log "waiting up to ${STARTUP_TIMEOUT_SECS}s for ${HOST}/api/ to return 200"
deadline=$(( $(date +%s) + STARTUP_TIMEOUT_SECS ))
ready=0
while (( $(date +%s) < deadline )); do
  if ! kill -0 "${WRANGLER_PID}" 2>/dev/null; then
    fail "wrangler dev exited before becoming ready"
    exit 1
  fi
  status=$(curl -s -o /dev/null -w '%{http_code}' "${HOST}/api/" || echo "000")
  if [[ "${status}" == "200" ]]; then
    ready=1
    break
  fi
  sleep 1
done
if [[ ${ready} -ne 1 ]]; then
  fail "wrangler dev did not become ready within ${STARTUP_TIMEOUT_SECS}s"
  exit 1
fi
log "wrangler dev ready"

# --- assertion helpers ----------------------------------------------------

# Check that the response status code matches and (optionally) that the
# body contains a substring. Captures both into temp files so we can
# print them on failure.
assert_response() {
  local label="$1"
  local method="$2"
  local path="$3"
  local expected_status="$4"
  local body_needle="${5:-}"
  local extra_args=("${@:6}")

  local body_file headers_file
  body_file=$(mktemp)
  headers_file=$(mktemp)

  local actual_status
  actual_status=$(
    curl -s -o "${body_file}" -D "${headers_file}" \
      -w '%{http_code}' \
      -X "${method}" \
      "${extra_args[@]}" \
      "${HOST}${path}"
  ) || actual_status="000"

  local pass=1
  if [[ "${actual_status}" != "${expected_status}" ]]; then
    pass=0
  fi
  if [[ -n "${body_needle}" ]] && ! grep -qF -- "${body_needle}" "${body_file}"; then
    pass=0
  fi

  if (( pass )); then
    ok "${label}  [${actual_status}] ${method} ${path}"
    PASSED=$((PASSED + 1))
  else
    fail "${label}  ${method} ${path}"
    fail "  expected status ${expected_status}, got ${actual_status}"
    if [[ -n "${body_needle}" ]]; then
      fail "  expected body to contain: ${body_needle}"
    fi
    fail "  --- response headers ---"
    sed 's/^/    /' "${headers_file}" >&2 || true
    fail "  --- response body (first 400 bytes) ---"
    head -c 400 "${body_file}" >&2 || true
    printf '\n' >&2
    FAILED=$((FAILED + 1))
  fi
  rm -f "${body_file}" "${headers_file}"
}

# Assert the body does NOT contain a needle. Used for the negative
# assertion that /api/bogus must NOT carry the Worker's JSON 404 shape.
assert_body_excludes() {
  local label="$1"
  local method="$2"
  local path="$3"
  local body_needle="$4"

  local body_file
  body_file=$(mktemp)
  curl -s -o "${body_file}" -X "${method}" "${HOST}${path}" || true

  if grep -qF -- "${body_needle}" "${body_file}"; then
    fail "${label}  ${method} ${path}"
    fail "  body unexpectedly contained: ${body_needle}"
    fail "  --- response body (first 400 bytes) ---"
    head -c 400 "${body_file}" >&2 || true
    printf '\n' >&2
    FAILED=$((FAILED + 1))
  else
    ok "${label}  ${method} ${path} (body excludes '${body_needle}')"
    PASSED=$((PASSED + 1))
  fi
  rm -f "${body_file}"
}

# --- contract assertions --------------------------------------------------

log "running 6 dispatch contract assertions"

# 1. /api/ -> static docs page (200, HTML containing the page identity).
assert_response "1. /api/ serves docs page" \
  GET "/api/" 200 "PURSUE://INDEX"

# 2. /api (no trailing slash) -> static docs page (trailingSlash: ignore).
#    -L because Astro may 308-redirect to /api/; either way the final
#    landing must be the docs page with status 200.
assert_response "2. /api (bare) serves docs page" \
  GET "/api" 200 "PURSUE://INDEX" -L

# 3. POST /api/retrieve with empty body -> 400 from worker/retrieve.js
#    (`query required`).
assert_response "3. POST /api/retrieve empty -> 400" \
  POST "/api/retrieve" 400 "query required" \
  -H "Content-Type: application/json" --data '{}'

# 4. POST /api/chat with empty body -> 400 from worker/chat.js.
assert_response "4. POST /api/chat empty -> 400" \
  POST "/api/chat" 400 "query required" \
  -H "Content-Type: application/json" --data '{}'

# 5. /api/bogus -> 404 from ASSETS, NOT the Worker's `{"error":"not found"}`
#    JSON body. We check status==404 AND that the body does not contain
#    the Worker's JSON shape — the static 404 page is HTML.
assert_response "5a. /api/bogus -> 404 status" \
  GET "/api/bogus" 404
assert_body_excludes "5b. /api/bogus body is NOT the worker's not-found JSON" \
  GET "/api/bogus" '"error":"not found"'

# 6. /api/changelog -> 404 (no static page, not in WORKER_API_PATHS).
#    Same shape as 5; this is a separate path because it's named in
#    PR #16 review as a forward-looking "could plausibly be a real page
#    one day" probe — if someone adds web/src/pages/api/changelog.astro,
#    update this script and the doc.
assert_response "6. /api/changelog -> 404" \
  GET "/api/changelog" 404

# --- summary --------------------------------------------------------------

log "summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  exit 1
fi
exit 0
