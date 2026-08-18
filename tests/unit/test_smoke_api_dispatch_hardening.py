"""Static-shape tests for the /api/* dispatch smoke harness (PR #19).

These tests are not integration tests — the smoke script's runtime
behavior is covered by the workflow itself when `wrangler dev` is
spun up in CI. What this file pins is the *hardening contract* added
in response to the PR #19 review:

    1. wrangler is a pinned devDependency of `web/` (not pulled at CI
       runtime via `npx --yes wrangler`).
    2. The smoke script honors `SMOKE_KEEP_LOG=1` so CI / local dev
       can preserve the wrangler dev log on failure.
    3. The readiness-poll curl has a per-iteration `--max-time` so a
       hung connection cannot eat the whole startup budget.
    4. Empty-array expansions use the bash-3.2-safe `${arr[@]+...}`
       idiom (macOS default-bash compat under `set -u`).
    5. The `-L` curl in assertion 2 has `--max-redirs` set.
    6. The smoke workflow's `paths:` filter includes
       `web/astro.config.mjs` and `web/package*.json`.
    7. `mktemp` invocations have explicit failure handling.
    8. Assertion 5b also asserts `Content-Type: text/html`.
    9. Script header has `set -e`.
   10. Script header documents `.dev.vars` secrets caveat.
   11. Cross-pointer between `web/scripts/test-api-page.mjs` and the
       smoke script.
   12. `WORKER_API_PATHS` declaration in `worker/index.js` references
       the smoke script.
   13. Failed local runs preserve a copy of the wrangler log to
       `/tmp/wrangler-smoke-last.log` and print the path.
   14. Script header documents the `wrangler dev` vs prod parity gap.

If a future edit accidentally regresses any of these, this test will
fail with a specific diagnostic pointing at the missing line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_api_dispatch.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "smoke-api-dispatch.yml"
WEB_PACKAGE_JSON = REPO_ROOT / "web" / "package.json"
WEB_TEST_API = REPO_ROOT / "web" / "scripts" / "test-api-page.mjs"
WORKER_INDEX = REPO_ROOT / "worker" / "index.js"


@pytest.fixture(scope="module")
def smoke_script_text() -> str:
    return SMOKE_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


# --- Finding 1: wrangler pinned in web/package.json -----------------------


def test_wrangler_pinned_as_web_dev_dependency() -> None:
    pkg = json.loads(WEB_PACKAGE_JSON.read_text(encoding="utf-8"))
    dev_deps = pkg.get("devDependencies", {})
    assert "wrangler" in dev_deps, (
        "wrangler must be a devDependency of web/ so the smoke harness "
        "uses the lockfile-pinned version, not whatever is current on "
        "npm at CI run time."
    )


def test_smoke_script_does_not_use_npx_yes_wrangler(smoke_script_text: str) -> None:
    # `--yes` makes sense only when npx is fetching at runtime; once
    # wrangler is a pinned devDep installed via `npm ci`, dropping
    # --yes makes the supply-chain posture explicit.
    assert "npx --yes wrangler" not in smoke_script_text, (
        "Drop `--yes` once wrangler is a pinned devDep; bare `npx wrangler` "
        "resolves from web/node_modules/.bin."
    )


def test_workflow_runs_npm_ci_before_smoke(workflow_text: str) -> None:
    # `npm ci` must come before the smoke step so the pinned wrangler
    # exists in node_modules. Compare positions of the actual run-step
    # tokens (`run: npm ci` and `bash scripts/smoke_api_dispatch.sh`)
    # rather than any prose mention of those strings in comments.
    npm_ci_pos = workflow_text.find("run: npm ci")
    smoke_run_pos = workflow_text.find("bash scripts/smoke_api_dispatch.sh")
    assert npm_ci_pos != -1, "Workflow must have a `run: npm ci` step."
    assert smoke_run_pos != -1, "Workflow must run the smoke script."
    assert npm_ci_pos < smoke_run_pos, (
        "`npm ci` must run before the smoke step so the pinned wrangler "
        "is installed."
    )


# --- Finding 2: failure log capture --------------------------------------


def test_smoke_script_honors_keep_log_env(smoke_script_text: str) -> None:
    assert "SMOKE_KEEP_LOG" in smoke_script_text, (
        "Script must honor SMOKE_KEEP_LOG=1 so the workflow can copy the "
        "log out before teardown deletes it."
    )


def test_workflow_uploads_wrangler_log_on_failure(workflow_text: str) -> None:
    assert "upload-artifact" in workflow_text, (
        "Workflow must upload-artifact the wrangler log on failure."
    )
    assert "SMOKE_KEEP_LOG" in workflow_text, (
        "Workflow must set SMOKE_KEEP_LOG=1 on the smoke step so the log "
        "survives the trap cleanup."
    )


# --- Finding 3: readiness curl --max-time --------------------------------


def test_readiness_curl_has_max_time(smoke_script_text: str) -> None:
    # Find the readiness poll's curl line and confirm --max-time is set.
    # The pattern below is the readiness probe specifically: it polls
    # "${HOST}/api/" inside a `while` loop.
    readiness_window = smoke_script_text.split("waiting up to")[1]
    readiness_window = readiness_window.split("wrangler dev ready")[0]
    assert "--max-time" in readiness_window, (
        "Readiness poll curl must set --max-time so a hung connection "
        "cannot eat the entire startup budget on one iteration."
    )


# --- Finding 4: bash-3.2 compat for empty-array expansion ----------------


def test_empty_array_expansion_uses_bash32_idiom(smoke_script_text: str) -> None:
    # Plain `"${extra_args[@]}"` under `set -u` errors on macOS bash 3.2
    # when the array is empty. The portable form is
    # `${extra_args[@]+"${extra_args[@]}"}`.
    assert "${extra_args[@]+" in smoke_script_text, (
        "extra_args expansion must use the ${arr[@]+...} guard idiom for "
        "bash-3.2 compat under `set -u`."
    )


# --- Finding 5: -L assertion has --max-redirs ----------------------------


def test_follow_redirects_assertion_has_max_redirs(smoke_script_text: str) -> None:
    # The only `-L` in the script is in assertion 2's extra_args. The
    # adjacent `--max-redirs N` flag prevents an unbounded redirect chain
    # from masking a dispatch problem.
    assert "--max-redirs" in smoke_script_text, (
        "The -L curl in assertion 2 must set --max-redirs."
    )


# --- Finding 6: workflow paths filter --------------------------------


def test_workflow_paths_includes_astro_config(workflow_text: str) -> None:
    assert "web/astro.config.mjs" in workflow_text, (
        "paths: filter must include web/astro.config.mjs — astro config "
        "controls trailingSlash semantics that assertion #2 depends on."
    )


def test_workflow_paths_includes_web_package_files(workflow_text: str) -> None:
    assert "web/package.json" in workflow_text
    assert "web/package-lock.json" in workflow_text, (
        "paths: filter must include web/package*.json — they control "
        "what builds web/dist/api/index.html, the smoke's own input."
    )


# --- Finding 7: mktemp failure handling -----------------------------------


def test_mktemp_invocations_have_failure_handling(smoke_script_text: str) -> None:
    # The two top-level mktemps are WRANGLER_LOG and PERSIST_DIR. Both
    # must abort cleanly if mktemp fails rather than letting later
    # `tail`/`rm` operate on empty paths.
    log_line_window = smoke_script_text.split("WRANGLER_LOG=")[1].split("\n")[0]
    persist_window = smoke_script_text.split("PERSIST_DIR=")[1].split("\n")[0]
    # Either an inline `|| { … exit 1; }` guard or a post-assignment
    # `[[ -n ... ]]` check counts.
    has_log_guard = "||" in log_line_window or "${WRANGLER_LOG:?}" in smoke_script_text
    has_persist_guard = (
        "||" in persist_window or "${PERSIST_DIR:?}" in smoke_script_text
    )
    assert has_log_guard, "WRANGLER_LOG mktemp must have failure handling"
    assert has_persist_guard, (
        "PERSIST_DIR mktemp must have failure handling"
    )


# --- Finding 8: assertion 5b also checks Content-Type --------------------


def test_assertion_5_checks_content_type_html(smoke_script_text: str) -> None:
    # The contract is "ASSETS-served HTML, not Worker-served JSON." The
    # body-excludes check is fragile on its own; pair it with a
    # Content-Type assertion that the response is text/html.
    assert "text/html" in smoke_script_text, (
        "Assertion 5 must also assert Content-Type starts with text/html."
    )


# --- Finding 9: set -e -----------------------------------------------------


def test_script_has_set_e(smoke_script_text: str) -> None:
    # Either `set -e` standalone or consolidated `set -euo pipefail`.
    # Scan the first ~100 lines so the parity / dev.vars caveats above
    # the `set` line are tolerated.
    head = "\n".join(smoke_script_text.splitlines()[:100])
    has_set_e = (
        "set -e\n" in head
        or "set -eu" in head
        or "set -euo" in head
    )
    assert has_set_e, "Script must include `set -e`"


# --- Finding 10: .dev.vars secrets caveat in script header ----------------


def test_script_header_documents_dev_vars_caveat(smoke_script_text: str) -> None:
    head = "\n".join(smoke_script_text.splitlines()[:80])
    assert ".dev.vars" in head, (
        "Script header must document the .dev.vars secrets caveat."
    )


# --- Finding 12: cross-pointer between web test and smoke script ---------


def test_web_api_page_test_references_smoke_script() -> None:
    text = WEB_TEST_API.read_text(encoding="utf-8")
    assert "smoke_api_dispatch.sh" in text, (
        "web/scripts/test-api-page.mjs must reference scripts/smoke_api_dispatch.sh "
        "so future editors find both halves of the /api contract test."
    )


def test_smoke_script_references_test_api_page(smoke_script_text: str) -> None:
    assert "test-api-page.mjs" in smoke_script_text, (
        "smoke script must reference web/scripts/test-api-page.mjs."
    )


# --- Finding 13: WORKER_API_PATHS comment references smoke script --------


def test_worker_api_paths_references_smoke_script() -> None:
    text = WORKER_INDEX.read_text(encoding="utf-8")
    # Confirm the smoke-script reference lives near the WORKER_API_PATHS
    # declaration (within ~25 lines above), so a human adding a new
    # path to the set sees it.
    lines = text.splitlines()
    decl_idx = next(
        (i for i, line in enumerate(lines) if "WORKER_API_PATHS" in line and "Set" in line),
        None,
    )
    assert decl_idx is not None
    window = "\n".join(lines[max(0, decl_idx - 25) : decl_idx + 1])
    assert "smoke_api_dispatch.sh" in window, (
        "Comment block above WORKER_API_PATHS must reference "
        "scripts/smoke_api_dispatch.sh so adding a route prompts a "
        "smoke-assertion update."
    )


# --- Finding 14: local repro preserves wrangler log on failure -----------


def test_failure_preserves_log_to_tmp(smoke_script_text: str) -> None:
    # On non-zero exit, the script should copy the log to
    # /tmp/wrangler-smoke-last.log and announce the path so a developer
    # who lost their scrollback has something to inspect.
    assert "wrangler-smoke-last.log" in smoke_script_text, (
        "On non-zero exit, the smoke script must preserve the log to "
        "/tmp/wrangler-smoke-last.log and print the path."
    )


# --- Finding 15: parity gap docs ------------------------------------------


def test_script_documents_wrangler_dev_parity_gap(smoke_script_text: str) -> None:
    head = "\n".join(smoke_script_text.splitlines()[:80])
    # Look for an explicit note about CORS / OPTIONS / 404-page semantics
    # NOT being exercised by wrangler dev. We accept any of the keywords
    # because the wording is flexible.
    has_parity_note = any(
        kw in head for kw in ("CORS", "OPTIONS", "404-page", "parity", "miniflare")
    )
    assert has_parity_note, (
        "Script header must document wrangler-dev vs prod parity gaps."
    )
