// Tests for build_csv_archive.mjs.
//
// The index's first entry is what /cite calls "the current manifest's
// CSV", so it must be the promoted manifest's csv_sha256 regardless of
// file mtimes (a fresh checkout gives every file the same mtime). The
// rest are ordered by the time each version was first observed, from
// the snapshot index, never by the filesystem.

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildCsvArchive } from "./build_csv_archive.mjs";

const SHA = {
  old: "a".repeat(64),
  mid: "b".repeat(64),
  cur: "c".repeat(64),
  unseen2: "e".repeat(64),
  unseen1: "d".repeat(64),
};

const FETCHED = {
  [SHA.old]: "2026-05-08T21:00:46Z",
  [SHA.mid]: "2026-07-10T12:01:00Z",
  [SHA.cur]: "2026-09-24T17:40:00Z",
};

function fixture({ manifestSha = SHA.cur, csvs = Object.values(SHA), mtime = new Date("2026-09-29T00:00:00Z") } = {}) {
  const root = mkdtempSync(join(tmpdir(), "csv-archive-"));
  const srcDir = join(root, "raw");
  mkdirSync(srcDir);
  for (const sha of csvs) {
    const p = join(srcDir, `${sha}.csv`);
    writeFileSync(p, `csv ${sha}\n`);
    utimesSync(p, mtime, mtime);
  }
  const manifestPath = join(root, "manifest.json");
  writeFileSync(manifestPath, JSON.stringify({ csv_sha256: manifestSha, cards: [] }));
  const snapshotIndexPath = join(root, "snapshots-index.json");
  writeFileSync(
    snapshotIndexPath,
    JSON.stringify({
      // Deliberately not in chronological order.
      snapshots: [SHA.mid, SHA.cur, SHA.old].map((s) => ({ csv_sha256: s, fetched_at: FETCHED[s] })),
    }),
  );
  const outDir = join(root, "out");
  const paths = { srcDir, outDir, manifestPath, snapshotIndexPath };
  return { root, paths };
}

function shas(index) {
  return index.csvs.map((e) => e.sha256);
}

describe("buildCsvArchive", () => {
  test("csvs[0] is the manifest's CSV when every file has the same mtime", () => {
    const { paths } = fixture({ manifestSha: SHA.mid });
    const index = buildCsvArchive(paths);
    assert.equal(index.csvs[0].sha256, SHA.mid);
  });

  test("orders by first-observed time newest-first, unseen versions last by sha", () => {
    const { paths } = fixture();
    const index = buildCsvArchive(paths);
    assert.deepEqual(shas(index), [SHA.cur, SHA.mid, SHA.old, SHA.unseen1, SHA.unseen2]);
    assert.equal(index.csvs[0].archived_at, FETCHED[SHA.cur]);
    assert.equal(index.csvs[2].archived_at, FETCHED[SHA.old]);
    assert.equal(index.csvs[3].archived_at, null);
  });

  test("mtimes do not affect the output", () => {
    const { paths } = fixture();
    const before = JSON.stringify(buildCsvArchive(paths).csvs);
    // Touch in reverse of first-observed order: oldest version newest on disk.
    const order = [SHA.cur, SHA.mid, SHA.old, SHA.unseen1, SHA.unseen2];
    order.forEach((sha, i) => {
      const t = new Date(Date.UTC(2026, 8, 29, 0, 0, i));
      utimesSync(join(paths.srcDir, `${sha}.csv`), t, t);
    });
    assert.equal(JSON.stringify(buildCsvArchive(paths).csvs), before);
  });

  test("the manifest's CSV is current even when it is older than other versions", () => {
    const { paths } = fixture({ manifestSha: SHA.old });
    assert.equal(buildCsvArchive(paths).csvs[0].sha256, SHA.old);
  });

  test("throws when the manifest's CSV is not in the archive", () => {
    const { paths } = fixture({ csvs: [SHA.old, SHA.mid] });
    assert.throws(() => buildCsvArchive(paths), /not in the CSV archive/);
  });

  test("writes the index and copies every CSV", () => {
    const { paths } = fixture();
    const index = buildCsvArchive(paths);
    const written = JSON.parse(readFileSync(join(paths.outDir, "index.json"), "utf8"));
    assert.deepEqual(written.csvs, index.csvs);
    for (const sha of Object.values(SHA)) {
      assert.equal(readFileSync(join(paths.outDir, `${sha}.csv`), "utf8"), `csv ${sha}\n`);
    }
  });
});
