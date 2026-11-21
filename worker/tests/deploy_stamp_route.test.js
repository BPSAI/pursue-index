// /deploy-stamp.json is a static asset: the Worker must hand it to ASSETS
// untouched (no alias, PDF, video or archive handler claims it), so the
// post-deploy verify can read which commit is live.

import { test } from "node:test";
import assert from "node:assert/strict";

import worker from "../index.js";

test("GET /deploy-stamp.json falls through to the static assets binding", async () => {
  const seen = [];
  const stamp = JSON.stringify({ schema: "pursue-deploy-stamp/v1", commit: "a".repeat(40) });
  const env = {
    ASSETS: {
      fetch: async (req) => {
        seen.push(new URL(req.url).pathname);
        return new Response(
          new URL(req.url).pathname === "/deploy-stamp.json" ? stamp : "{}",
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      },
    },
    PDFS: {
      get: async () => assert.fail("the stamp path must never reach R2"),
      head: async () => assert.fail("the stamp path must never reach R2"),
    },
  };
  const res = await worker.fetch(new Request("https://pursueindex.com/deploy-stamp.json"), env);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), stamp);
  assert.ok(seen.includes("/deploy-stamp.json"));
});
