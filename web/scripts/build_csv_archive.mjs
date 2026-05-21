#!/usr/bin/env node
/**
 * build_csv_archive — copy the upstream-CSV archive into the public/
 * tree at build time, and emit an index.json that lists every archived
 * version (sha, byte size, mtime).
 *
 * The CSV is the load-bearing input for every "this card was in the
 * manifest" claim; anyone reproducing our work needs the exact bytes
 * that produced a given manifest sha. Distinct CSVs land in
 * ``data/raw/csv/<sha>.csv``; this build step exposes them at
 * ``/data/csv/<sha>.csv`` for citation reproducibility.
 *
 * Idempotent: source-of-truth is ``data/raw/csv/``. Re-running copies
 * any new shas + rewrites the index.json.
 *
 * Output:
 *   web/public/data/csv/<sha>.csv     (one per archived CSV)
 *   web/public/data/csv/index.json    (machine-readable inventory)
 */

import { existsSync, readdirSync, statSync, copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname, basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");
const SRC_DIR = join(REPO_ROOT, "data", "raw", "csv");
const OUT_DIR = join(REPO_ROOT, "web", "public", "data", "csv");

if (!existsSync(SRC_DIR)) {
  console.error(`build_csv_archive: source dir missing: ${SRC_DIR}`);
  process.exit(0);  // No CSVs to archive — not an error.
}

mkdirSync(OUT_DIR, { recursive: true });

const csvFiles = readdirSync(SRC_DIR).filter((f) => f.endsWith(".csv"));

const entries = [];
for (const fname of csvFiles) {
  const sha = basename(fname, ".csv");
  const src = join(SRC_DIR, fname);
  const dst = join(OUT_DIR, fname);
  const stat = statSync(src);
  copyFileSync(src, dst);
  entries.push({
    sha256: sha,
    bytes: stat.size,
    archived_at: stat.mtime.toISOString(),
    url: `/data/csv/${fname}`,
  });
}

// Sort newest-first by mtime so the freshest CSV is at the top.
entries.sort((a, b) => (a.archived_at < b.archived_at ? 1 : -1));

const index = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  source_url: "https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-release001.csv",
  source_notes:
    "Distinct CSV versions are archived locally and exposed here for " +
    "citation reproducibility. Each row's sha256 is the load-bearing " +
    "identifier — verify any download with `shasum -a 256 <file>` " +
    "against the filename or against this index's `sha256` field.",
  csvs: entries,
};
writeFileSync(join(OUT_DIR, "index.json"), JSON.stringify(index, null, 2) + "\n");

console.log(
  `build_csv_archive: copied ${entries.length} CSV(s) to /data/csv/; ` +
  `latest sha ${entries[0]?.sha256.slice(0, 12) ?? "(none)"}`,
);
