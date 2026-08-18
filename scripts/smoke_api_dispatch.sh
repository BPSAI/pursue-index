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
#                          `{"error":"not found"}` JSON), Content-Type
#                          starting with `text/html`.
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
#   0 - all assertions passed
#   1 - any assertion failed, or wrangler dev did not come up in time
#
# Environment knobs:
#   SMOKE_PORT                 - listen port (default 8788)
#   SMOKE_STARTUP_TIMEOUT_SECS - readiness budget (default 60)
#   SMOKE_KEEP_LOG=1           - skip wrangler log deletion in cleanup,
#                                so CI can upload-artifact it. The
#                                workflow at .github/workflows/smoke-api-
#                                dispatch.yml sets this on the smoke step.
#
# Local-failure UX: on non-zero exit the wrangler dev log is also
# preserved at `/tmp/wrangler-smoke-last.log` and the path is printed to
# stderr, so a developer who scrolled past the in-band tail can still
# inspect the full log after the script exits.
#
# See also: web/scripts/test-api-page.mjs — the static-HTML snapshot test
# that asserts the /api docs page contents. This smoke script asserts
# *dispatch behavior*; the two are complementary halves of the /api
# contract gate.
#
# Requirements: bash, curl, Node 22+, and a wrangler installed at
# `web/node_modules/.bin/wrangler`. The CI workflow runs `npm ci` in
# `web/` before this script so the pinned wrangler devDependency is
# present. Locally, run `(cd web && npm ci)` first.
#
# .dev.vars caveat: wrangler dev binds local secrets from
# `web/.dev.vars` if present. Do NOT keep live
# Voyage / Anthropic / Cloudflare keys in `.dev.vars` while running this
# smoke test — on assertion failure the cleanup trap dumps the last 80
# lines of the wrangler dev log to stderr (and to the kept-log path
# above), and any secret that wrangler echoed during request processing
# would land in those bytes. CI runs in `--local` mode with no real
# `.dev.vars`, so this is a local-dev hazard only.
#
# Parity caveat: `wrangler dev --local` emulates the Worker via
# miniflare, which does NOT exercise prod-edge
# behaviors that include OPTIONS/CORS preflight handling and the
# `not_found_handling: "404-page"` semantics declared in `wrangler.jsonc`.
# Those surfaces are covered by the Worker unit tests in
# `worker/tests/api_gate.test.js` and by the deployed-prod smoke checks
# the operator runs after `wrangler deploy`. Treat this script as the
# dispatch-contract gate, not a full prod-parity gate.

# Hardened bash. `set -e` aborts on unexpected failures (mktemp, curl
# crashes, etc.). `set -u` catches unset-variable typos. `pipefail`
# propagates failures through pipelines. The assertion helpers
# (assert_response, assert_body_excludes) explicitly count pass/fail
# and always return 0, so they are exempt from `set -e` early-exit.
set -euo pipefail

# --- config ---------------------------------------------------------------

PORT="${SMOKE_PORT:-8788}"
HOST="http://127.0.0.1:${PORT}"
STARTUP_TIMEOUT_SECS="${SMOKE_STARTUP_TIMEOUT_SECS:-60}"
SMOKE_KEEP_LOG="${SMOKE_KEEP_LOG:-0}"
KEPT_LOG_PATH="/tmp/wrangler-smoke-last.log"

WRANGLER_LOG="$(mktemp -t wrangler-smoke-XXXXXX.log)" || {
  printf '[smoke] FAIL: mktemp failed for wrangler log\n' >&2
  exit 1
}
PERSIST_DIR="$(mktemp -d -t wrangler-smoke-persist-XXXXXX)" || {
  printf '[smoke] FAIL: mktemp -d failed for persist dir\n' >&2
  rm -f "${WRANGLER_LOG}" 2>/dev/null || true
  exit 1
}

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
    # Also preserve the full log to a stable path for local-dev repro
    # and for the CI upload-artifact step (gated on SMOKE_KEEP_LOG).
    if [[ -f "${WRANGLER_LOG}" ]]; then
      cp "${WRANGLER_LOG}" "${KEPT_LOG_PATH}" 2>/dev/null || true
      log "full wrangler log preserved at ${KEPT_LOG_PATH}"
      if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
        cp "${WRANGLER_LOG}" "${GITHUB_WORKSPACE}/wrangler-smoke.log" 2>/dev/null || true
      fi
    fi
  fi
  rm -rf "${PERSIST_DIR}" 2>/dev/null || true
  if [[ "${SMOKE_KEEP_LOG}" != "1" ]]; then
    rm -f "${WRANGLER_LOG}" 2>/dev/null || true
  else
    log "SMOKE_KEEP_LOG=1; preserving ${WRANGLER_LOG}"
  fi
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
if [[ ! -x "${REPO_ROOT}/web/node_modules/.bin/wrangler" ]] \
  && [[ ! -d "${REPO_ROOT}/web/node_modules/wrangler" ]]; then
  fail "wrangler not found in web/node_modules. Run: (cd web && npm ci) first."
  exit 1
fi

# --- start wrangler dev ---------------------------------------------------

log "starting wrangler dev on port ${PORT} (log: ${WRANGLER_LOG})"
# `setsid` puts wrangler in its own process group so we can kill the
# whole tree (wrangler -> workerd) at teardown. --local + --persist-to
# /tmp keep it self-contained and avoid touching the operator's
# .wrangler cache. We invoke the locally-installed wrangler binary
# directly from web/node_modules/.bin/ rather than fetching at runtime,
# so the version is whatever web/package.json + web/package-lock.json
# have pinned. cwd is the repo root so `wrangler.jsonc`'s relative
# paths resolve correctly.
WRANGLER_BIN="${REPO_ROOT}/web/node_modules/.bin/wrangler"
(
  cd "${REPO_ROOT}"
  setsid "${WRANGLER_BIN}" dev \
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
# `--max-time 5` per probe: a hung connection cannot eat the entire
# startup budget on a single iteration; we'll loop and try again
# instead.
log "waiting up to ${STARTUP_TIMEOUT_SECS}s for ${HOST}/api/ to return 200"
deadline=$(( $(date +%s) + STARTUP_TIMEOUT_SECS ))
ready=0
while (( $(date +%s) < deadline )); do
  if ! kill -0 "${WRANGLER_PID}" 2>/dev/null; then
    fail "wrangler dev exited before becoming ready"
    exit 1
  fi
  status=$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' "${HOST}/api/" || echo "000")
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
#
# `extra_args` is expanded with the `${arr[@]+"${arr[@]}"}` idiom rather
# than the bare `"${arr[@]}"` so that an empty array under `set -u` does
# NOT trip "unbound variable" on macOS bash 3.2. bash 4.4+ tolerates
# the bare form; this idiom is portable across both.
assert_response() {
  local label="$1"
  local method="$2"
  local path="$3"
  local expected_status="$4"
  local body_needle="${5:-}"
  local extra_args=("${@:6}")

  local body_file headers_file
  body_file=$(mktemp) || { fail "mktemp failed in assert_response"; FAILED=$((FAILED + 1)); return 0; }
  headers_file=$(mktemp) || { fail "mktemp failed in assert_response"; rm -f "${body_file}"; FAILED=$((FAILED + 1)); return 0; }

  local actual_status
  actual_status=$(
    curl -s --max-time 10 -o "${body_file}" -D "${headers_file}" \
      -w '%{http_code}' \
      -X "${method}" \
      ${extra_args[@]+"${extra_args[@]}"} \
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

# Assert the body does NOT contain a needle AND that Content-Type starts
# with the given prefix (or skip the CT check if "" is passed). Used for
# the negative assertion that /api/bogus must NOT carry the Worker's JSON
# 404 shape and MUST be ASSETS-served HTML.
assert_body_excludes() {
  local label="$1"
  local method="$2"
  local path="$3"
  local body_needle="$4"
  local content_type_prefix="${5:-}"

  local body_file headers_file
  body_file=$(mktemp) || { fail "mktemp failed in assert_body_excludes"; FAILED=$((FAILED + 1)); return 0; }
  headers_file=$(mktemp) || { fail "mktemp failed in assert_body_excludes"; rm -f "${body_file}"; FAILED=$((FAILED + 1)); return 0; }

  curl -s --max-time 10 -o "${body_file}" -D "${headers_file}" \
    -X "${method}" "${HOST}${path}" || true

  local pass=1
  local fail_reason=""

  if grep -qF -- "${body_needle}" "${body_file}"; then
    pass=0
    fail_reason="body unexpectedly contained: ${body_needle}"
  fi

  if [[ -n "${content_type_prefix}" ]]; then
    # Match `Content-Type:` case-insensitively, strip leading whitespace,
    # and check the prefix.
    local ct_line
    ct_line=$(grep -i '^content-type:' "${headers_file}" | head -n 1 || true)
    local ct_value
    ct_value=$(printf '%s' "${ct_line}" | sed -e 's/^[Cc]ontent-[Tt]ype:[[:space:]]*//')
    if [[ "${ct_value}" != "${content_type_prefix}"* ]]; then
      pass=0
      fail_reason="${fail_reason:+${fail_reason}; }expected Content-Type starting with '${content_type_prefix}', got '${ct_value}'"
    fi
  fi

  if (( pass )); then
    if [[ -n "${content_type_prefix}" ]]; then
      ok "${label}  ${method} ${path} (excludes '${body_needle}', Content-Type '${content_type_prefix}*')"
    else
      ok "${label}  ${method} ${path} (body excludes '${body_needle}')"
    fi
    PASSED=$((PASSED + 1))
  else
    fail "${label}  ${method} ${path}"
    fail "  ${fail_reason}"
    fail "  --- response headers ---"
    sed 's/^/    /' "${headers_file}" >&2 || true
    fail "  --- response body (first 400 bytes) ---"
    head -c 400 "${body_file}" >&2 || true
    printf '\n' >&2
    FAILED=$((FAILED + 1))
  fi
  rm -f "${body_file}" "${headers_file}"
}

# --- contract assertions --------------------------------------------------

log "running dispatch contract assertions"

# 1. /api/ -> static docs page (200, HTML containing the page identity).
assert_response "1. /api/ serves docs page" \
  GET "/api/" 200 "PURSUE://INDEX"

# 2. /api (no trailing slash) -> static docs page (trailingSlash: ignore).
#    -L because Astro may 308-redirect to /api/; either way the final
#    landing must be the docs page with status 200. `--max-redirs 3`
#    bounds the redirect chain so a misconfigured Astro redirect loop
#    can't masquerade as a dispatch problem.
assert_response "2. /api (bare) serves docs page" \
  GET "/api" 200 "PURSUE://INDEX" -L --max-redirs 3

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
#    the Worker's JSON shape AND that Content-Type starts with text/html
#    — the contract is "ASSETS-served HTML, not Worker-served JSON,"
#    and substring exclusion alone is fragile (a future
#    Astro 404 could coincidentally avoid the substring).
assert_response "5a. /api/bogus -> 404 status" \
  GET "/api/bogus" 404
assert_body_excludes "5b. /api/bogus body is HTML 404, NOT worker JSON" \
  GET "/api/bogus" '"error":"not found"' "text/html"

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
