// Snapshot test for /api documentation page.
//
// Asserts that `npm run build` produced web/dist/api/index.html and that
// the page contains every section the API docs are expected to document.
// This is the closest thing the web/ package has to a renderer test —
// the underlying assumption is that if the static HTML contains all of
// the section markers, all of the curl examples, and the rate-limit
// numbers we sourced from the worker, the page will be intelligible to
// a researcher landing cold.
//
// Two-direction drift detection:
//   1. Forward (REQUIRED_FRAGMENTS): doc removes a section/event/number
//      → test fails. Catches accidental deletions during edits.
//   2. Backward (CONSTANT_ASSERTIONS): worker constants change but doc
//      doesn't → test fails. Imports the actual values from
//      `worker/chat_kv.js` and `worker/chat.js` so a constant flip on
//      the worker side surfaces here loudly. Closes the gap flagged in
//      PR #4 review (snapshot caught only forward drift).
//
// See also: `scripts/smoke_api_dispatch.sh` — the integration smoke
// that asserts the *dispatch behavior* of /api/* (Worker handlers vs.
// ASSETS-served static page). This file asserts the static-HTML
// contents; the smoke asserts the Worker dispatcher routes the right
// requests to the right backend. The two are complementary halves of
// the /api contract gate.

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { RATE_LIMIT, DAILY_BUDGET_USD } from "../../worker/chat_kv.js";

const PAGE_PATH = resolve(
  new URL(".", import.meta.url).pathname,
  "..",
  "dist",
  "api",
  "index.html",
);

const REQUIRED_FRAGMENTS = [
  // page identity
  "PURSUE://INDEX",
  "API",
  // section headings
  "Surface overview",
  "/api/retrieve",
  "/api/chat",
  "Citation contract",
  "Errors",
  "License",
  // CORS — outcome framing, not bypass mechanics
  "pursueindex.com",
  "www.pursueindex.com",
  "supported",
  // curl examples
  "curl",
  "Content-Type: application/json",
  // SSE event names
  "event: citations",
  "event: text",
  "event: done",
  "event: error",
  // SSE event-done flags
  "cached: true",
  "abstained: true",
  // 429 body shape + retry semantics
  "current count",
  "Retry-After",
  // 405 row
  "405",
  "method not allowed",
  // model-name caveat — phrase survives Astro whitespace
  "exact model may be",
  "worker/chat.js",
  "DEFAULT_MODEL",
  // citation format from chat_prompt.js
  "[card_id:page]",
  // BYOK pointer
  "BYOK",
  "anthropic-dangerous-direct-browser-access",
];

// Backward-drift guard: the doc must contain whatever the worker says
// today. If a worker constant changes, the test fails immediately and
// the doc has to be updated before merge.
const CONSTANT_ASSERTIONS = [
  {
    label: "worker RATE_LIMIT",
    needle: `${RATE_LIMIT} chats`,
    hint: "Update web/src/pages/api.astro to match worker/chat_kv.js#RATE_LIMIT",
  },
  {
    label: "worker DAILY_BUDGET_USD",
    needle: `$${DAILY_BUDGET_USD}`,
    hint: "Update web/src/pages/api.astro to match worker/chat_kv.js#DAILY_BUDGET_USD",
  },
];

async function main() {
  let html;
  try {
    html = await readFile(PAGE_PATH, "utf8");
  } catch (err) {
    console.error(`FAIL: ${PAGE_PATH} not found. Run \`npm run build\` first.`);
    console.error(String(err.message || err));
    process.exit(1);
  }

  const missingFragments = REQUIRED_FRAGMENTS.filter((f) => !html.includes(f));
  const failedConstants = CONSTANT_ASSERTIONS.filter(
    (c) => !html.includes(c.needle),
  );

  if (missingFragments.length > 0 || failedConstants.length > 0) {
    if (missingFragments.length > 0) {
      console.error("FAIL: /api page is missing required fragments:");
      for (const m of missingFragments) console.error("  -", m);
    }
    if (failedConstants.length > 0) {
      console.error("FAIL: /api page is out of sync with worker constants:");
      for (const c of failedConstants) {
        console.error(`  - ${c.label}: missing "${c.needle}"`);
        console.error(`    ${c.hint}`);
      }
    }
    process.exit(1);
  }

  console.log(
    `PASS: /api page (${html.length} bytes) contains all ${REQUIRED_FRAGMENTS.length} required fragments and ${CONSTANT_ASSERTIONS.length} worker-constant assertions.`,
  );
}

main();
