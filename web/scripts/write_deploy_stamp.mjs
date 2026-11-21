// Write public/deploy-stamp.json: which commit built this deploy.
//
// Cloudflare Workers Builds exposes the built commit as WORKERS_CI_COMMIT_SHA.
// The post-deploy verify reads this file from the live site and requires it to
// equal the pushed commit, so a stale deploy cannot pass for a new one.
// Without a commit (a local build) nothing is written.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCHEMA = "pursue-deploy-stamp/v1";
const DEFAULT_OUT = resolve(dirname(fileURLToPath(import.meta.url)), "../public/deploy-stamp.json");

export function writeDeployStamp({ env = process.env, outPath = DEFAULT_OUT } = {}) {
  const commit = env.WORKERS_CI_COMMIT_SHA;
  if (!commit || !/^[0-9a-f]{40}$/.test(commit)) {
    console.warn("deploy-stamp: no 40-hex WORKERS_CI_COMMIT_SHA; not writing a stamp");
    return false;
  }
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, JSON.stringify({ schema: SCHEMA, commit }) + "\n");
  return true;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  writeDeployStamp();
}
