// Snapshot test for /api documentation page.
//
// Asserts that `npm run build` produced web/dist/api/index.html and that
// the page contains every section the API docs are expected to document.
// This is the closest thing the web/ package has to a renderer test —
// the underlying assumption is that if the static HTML contains all of
// the section markers, all of the curl examples, and the rate-limit
// numbers we sourced from the worker, the page will be intelligible to
// a researcher landing cold.

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

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
  // hard-coded numbers from worker/chat_kv.js
  "5 chats",
  "$100",
  // CORS
  "pursueindex.com",
  "www.pursueindex.com",
  // curl examples
  "curl",
  "Content-Type: application/json",
  // SSE event names
  "event: citations",
  "event: text",
  "event: done",
  "event: error",
  // citation format from chat_prompt.js
  "[card_id:page]",
  // BYOK pointer
  "BYOK",
  "anthropic-dangerous-direct-browser-access",
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
  const missing = REQUIRED_FRAGMENTS.filter((f) => !html.includes(f));
  if (missing.length > 0) {
    console.error("FAIL: /api page is missing required fragments:");
    for (const m of missing) console.error("  -", m);
    process.exit(1);
  }
  console.log(
    `PASS: /api page (${html.length} bytes) contains all ${REQUIRED_FRAGMENTS.length} required fragments.`,
  );
}

main();
