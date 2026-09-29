// Cold-path memory budget for /api/retrieve and /api/chat.
//
// Workers isolates are capped at 128 MB, and the limit is enforced on the
// isolate as a whole (heap plus array buffers), not on process RSS. A cold
// retrieval over the committed corpus must stay within half of that, so a
// warm isolate's other allocations and corpus growth still have headroom.
// The probe runs in a child process with --expose-gc; see
// tests/support/cold_memory_probe.js for what it samples and where.

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const BUDGET_BYTES = 64 * 1024 * 1024;

test("a cold retrieval over the committed corpus peaks under 64 MiB", () => {
  const out = execFileSync(
    process.execPath,
    ["--expose-gc", path.join(here, "support", "cold_memory_probe.js")],
    { encoding: "utf8", maxBuffer: 1 << 20, timeout: 300_000 },
  );
  const r = JSON.parse(out.trim().split("\n").at(-1));
  const mib = (b) => (b / 2 ** 20).toFixed(1);
  console.log(`cold retrieval peak: ${mib(r.peakDelta)} MiB over a ${mib(r.baseline)} MiB baseline`);
  assert.ok(r.passages > 0, "the probe retrieved passages (the cold path actually ran)");
  assert.ok(
    r.peakDelta <= BUDGET_BYTES,
    `cold retrieval peaked at ${mib(r.peakDelta)} MiB, budget ${mib(BUDGET_BYTES)} MiB`,
  );
});
