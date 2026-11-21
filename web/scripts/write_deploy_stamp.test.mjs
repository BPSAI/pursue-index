// Tests for write_deploy_stamp.mjs: the served record of which commit built
// this deploy, read back by the post-deploy verify.

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

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

  test("unset env var logs the exact reason and writes nothing", () => {
    const out = join(mkdtempSync(join(tmpdir(), "stamp-")), "deploy-stamp.json");
    const logs = [];
    writeDeployStamp({ env: {}, outPath: out, log: (m) => logs.push(m) });
    assert.deepEqual(logs, ["no stamp: WORKERS_CI_COMMIT_SHA unset"]);
    assert.equal(existsSync(out), false);
  });

  test("invalid env var logs the exact reason", () => {
    const out = join(mkdtempSync(join(tmpdir(), "stamp-")), "deploy-stamp.json");
    const logs = [];
    writeDeployStamp({ env: { WORKERS_CI_COMMIT_SHA: "main" }, outPath: out, log: (m) => logs.push(m) });
    assert.deepEqual(logs, ["no stamp: WORKERS_CI_COMMIT_SHA invalid"]);
  });

  test("the CLI prints the message on stderr and exits 0", () => {
    const script = join(dirname(fileURLToPath(import.meta.url)), "write_deploy_stamp.mjs");
    const env = { ...process.env };
    delete env.WORKERS_CI_COMMIT_SHA;
    const r = spawnSync(process.execPath, [script], { env, encoding: "utf8" });
    assert.equal(r.status, 0);
    assert.match(r.stderr, /no stamp: WORKERS_CI_COMMIT_SHA unset/);
  });
});
