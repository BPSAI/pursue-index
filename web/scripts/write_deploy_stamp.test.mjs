// Tests for write_deploy_stamp.mjs: the served record of which commit built
// this deploy, read back by the post-deploy verify.

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { writeDeployStamp } from "./write_deploy_stamp.mjs";

const SHA = "d".repeat(40);

describe("writeDeployStamp", () => {
  test("writes the commit from the Workers Builds env var", () => {
    const out = join(mkdtempSync(join(tmpdir(), "stamp-")), "deploy-stamp.json");
    assert.equal(writeDeployStamp({ env: { WORKERS_CI_COMMIT_SHA: SHA }, outPath: out }), true);
    assert.deepEqual(JSON.parse(readFileSync(out, "utf8")), { schema: "pursue-deploy-stamp/v1", commit: SHA });
  });

  test("writes nothing without a commit env var", () => {
    const out = join(mkdtempSync(join(tmpdir(), "stamp-")), "deploy-stamp.json");
    assert.equal(writeDeployStamp({ env: {}, outPath: out }), false);
    assert.equal(existsSync(out), false);
  });

  test("refuses a value that is not a 40-hex sha", () => {
    const out = join(mkdtempSync(join(tmpdir(), "stamp-")), "deploy-stamp.json");
    assert.equal(writeDeployStamp({ env: { WORKERS_CI_COMMIT_SHA: "main" }, outPath: out }), false);
    assert.equal(existsSync(out), false);
  });
});
