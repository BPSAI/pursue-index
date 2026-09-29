#!/usr/bin/env node
/**
 * build_csv_archive — copy the upstream-CSV archive into the public/
 * tree at build time, and emit an index.json that lists every archived
 * version (sha, byte size, first-observed time).
 *
 * The CSV is the load-bearing input for every "this card was in the
 * manifest" claim; anyone reproducing our work needs the exact bytes
 * that produced a given manifest sha. Distinct CSVs land in
 * ``data/raw/csv/<sha>.csv``; this build step exposes them at
 * ``/data/csv/<sha>.csv`` for citation reproducibility.
 *
 * Ordering is checkout-independent (this runs as `prebuild` on every
 * deploy, where every file has the same mtime):
 *   1. ``csvs[0]`` is the build manifest's ``csv_sha256`` — /cite names
 *      it as the CSV the current manifest is built from. A manifest
 *      whose CSV is not archived fails the build.
 *   2. The rest are newest-first by the time each version was first
 *      observed (``fetched_at`` in the snapshot index), which is also
 *      what ``archived_at`` reports.
 *   3. Versions with no snapshot (never promoted to a manifest) follow,
 *      by sha, with ``archived_at: null``.
 *
 * Idempotent: source-of-truth is ``data/raw/csv/``. Re-running copies
 * any new shas + rewrites the index.json.
 *
 * Output:
 *   web/public/data/csv/<sha>.csv     (one per archived CSV)
 *   web/public/data/csv/index.json    (machine-readable inventory)
 */

import { existsSync, readdirSync, readFileSync, statSync, copyFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname, basename, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..", "..");

export const DEFAULT_PATHS = {
  srcDir: join(REPO_ROOT, "data", "raw", "csv"),
  outDir: join(REPO_ROOT, "web", "public", "data", "csv"),
  // The same manifest the Astro build renders (a byte-mirror of
  // data/manifests/latest.json, enforced by test_snapshot_mirror_coverage).
  manifestPath: join(REPO_ROOT, "web", "src", "data", "manifest.json"),
  snapshotIndexPath: join(REPO_ROOT, "data", "manifests", "snapshots", "index.json"),
};

function firstObserved(snapshotIndexPath) {
  const out = new Map();
  for (const s of JSON.parse(readFileSync(snapshotIndexPath, "utf8")).snapshots) {
    const prev = out.get(s.csv_sha256);
    if (prev === undefined || s.fetched_at < prev) out.set(s.csv_sha256, s.fetched_at);
  }
  return out;
}

export function buildCsvArchive({ srcDir, outDir, manifestPath, snapshotIndexPath }) {
  const currentSha = JSON.parse(readFileSync(manifestPath, "utf8")).csv_sha256;
  const observed = firstObserved(snapshotIndexPath);
  const csvFiles = readdirSync(srcDir).filter((f) => f.endsWith(".csv"));
  if (!csvFiles.includes(`${currentSha}.csv`)) {
    throw new Error(
      `build_csv_archive: manifest csv_sha256 ${currentSha} is not in the CSV archive (${srcDir})`,
    );
  }

  mkdirSync(outDir, { recursive: true });
  const entries = [];
  for (const fname of csvFiles) {
    const sha = basename(fname, ".csv");
    const src = join(srcDir, fname);
    copyFileSync(src, join(outDir, fname));
    entries.push({
      sha256: sha,
      bytes: statSync(src).size,
      archived_at: observed.get(sha) ?? null,
      url: `/data/csv/${fname}`,
    });
  }

  const rank = (e) => (e.sha256 === currentSha ? 0 : e.archived_at !== null ? 1 : 2);
  entries.sort((a, b) => {
    const r = rank(a) - rank(b);
    if (r !== 0) return r;
    if (a.archived_at !== b.archived_at) return a.archived_at < b.archived_at ? 1 : -1;
    return a.sha256 < b.sha256 ? -1 : 1;
  });

  const index = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    source_url: "https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-data.csv",
    source_notes:
      "Distinct CSV versions are archived locally and exposed here for " +
      "citation reproducibility. Each row's sha256 is the load-bearing " +
      "identifier — verify any download with `shasum -a 256 <file>` " +
      "against the filename or against this index's `sha256` field.",
    csvs: entries,
  };
  writeFileSync(join(outDir, "index.json"), JSON.stringify(index, null, 2) + "\n");
  return index;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!existsSync(DEFAULT_PATHS.srcDir)) {
    console.error(`build_csv_archive: source dir missing: ${DEFAULT_PATHS.srcDir}`);
    process.exit(0);  // No CSVs to archive — not an error.
  }
  const index = buildCsvArchive(DEFAULT_PATHS);
  const unseen = index.csvs.filter((e) => e.archived_at === null).map((e) => e.sha256.slice(0, 12));
  console.log(
    `build_csv_archive: copied ${index.csvs.length} CSV(s) to /data/csv/; ` +
    `current sha ${index.csvs[0].sha256.slice(0, 12)}` +
    (unseen.length ? `; not in snapshot index: ${unseen.join(", ")}` : ""),
  );
}
