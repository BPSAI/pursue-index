// Tests for build_byte_history.mjs.
//
// Sprint 4g Phase 3. The script reads data/asset-bytes-registry.jsonl
// and emits a card_id → ordered byte-history map for the card-detail
// banner + the /altered page. Only cards with >1 byte_sha appear in
// the output — the on-page banner only fires on those, and bundling
// the single-sha cards would inflate the JSON ~3× for no consumer.

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildByteHistory } from "./build_byte_history.mjs";

function makeTmpDir() {
  const dir = join(tmpdir(), `byte-history-test-${Math.random().toString(36).slice(2)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

function writeRegistry(path, rows) {
  const lines = rows.map((r) => JSON.stringify(r)).join("\n") + "\n";
  writeFileSync(path, lines, "utf-8");
}

describe("buildByteHistory — pure transform", () => {
  test("includes only cards with >1 byte_sha", () => {
    const rows = [
      { card_id: "single", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/aaaa.pdf", asset_filename: "x.pdf" },
      { card_id: "multi", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/bbbb.pdf", asset_filename: "y.pdf" },
      { card_id: "multi", byte_sha256: "c".repeat(64), byte_size: 150, fetched_at: "2026-05-14T00:00:00Z", archive_key: "archive/cccc.pdf", asset_filename: "y.pdf" },
    ];
    const out = buildByteHistory(rows);
    assert.ok(out.multi);
    assert.ok(!out.single);
    assert.equal(out.multi.length, 2);
  });

  test("entries are ordered newest-first (latest fetched_at at index 0)", () => {
    const rows = [
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/aaaa.pdf", asset_filename: "f.pdf" },
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-14T00:00:00Z", archive_key: "archive/bbbb.pdf", asset_filename: "f.pdf" },
    ];
    const out = buildByteHistory(rows);
    assert.equal(out.x[0].byte_sha256, "b".repeat(64));
    assert.equal(out.x[1].byte_sha256, "a".repeat(64));
  });

  test("flags the current (newest) entry with is_current=true", () => {
    const rows = [
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/aaaa.pdf", asset_filename: "f.pdf" },
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-14T00:00:00Z", archive_key: "archive/bbbb.pdf", asset_filename: "f.pdf" },
    ];
    const out = buildByteHistory(rows);
    assert.equal(out.x[0].is_current, true);
    assert.equal(out.x[1].is_current, false);
  });

  test("preserves all fields needed for the banner + /altered table", () => {
    const rows = [
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/aaaa.pdf", asset_filename: "doc.pdf" },
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-14T00:00:00Z", archive_key: "archive/bbbb.pdf", asset_filename: "doc.pdf" },
    ];
    const out = buildByteHistory(rows);
    const entry = out.x[0];
    assert.ok(entry.byte_sha256);
    assert.ok(typeof entry.byte_size === "number");
    assert.ok(entry.fetched_at);
    assert.ok(entry.archive_key);
    assert.ok(entry.asset_filename);
    assert.ok(typeof entry.is_current === "boolean");
  });

  test("empty input → empty map", () => {
    assert.deepEqual(buildByteHistory([]), {});
  });

  test("deterministic: same input → byte-identical output", () => {
    const rows = [
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/aaaa.pdf", asset_filename: "f.pdf" },
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-14T00:00:00Z", archive_key: "archive/bbbb.pdf", asset_filename: "f.pdf" },
    ];
    const a = JSON.stringify(buildByteHistory(rows));
    const b = JSON.stringify(buildByteHistory(rows));
    assert.equal(a, b);
  });
});

describe("buildByteHistory — live registry shape", () => {
  test("handles the canonical registry row shape from asset-bytes-registry.jsonl", () => {
    // Verbatim shape per `head -1 data/asset-bytes-registry.jsonl`.
    const row = {
      card_id: "7d58f0cac741650a",
      asset_url: "https://www.war.gov/medialink/ufo/x.pdf",
      asset_filename: "x.pdf",
      byte_sha256: "a".repeat(64),
      byte_size: 100,
      upstream_etag: '"abc"',
      archive_key: "archive/" + "a".repeat(64) + ".pdf",
      current_key: "7d58f0cac741650a.pdf",
      fetched_at: "2026-05-12T02:15:33.899525+00:00",
    };
    const out = buildByteHistory([row, { ...row, byte_sha256: "b".repeat(64), fetched_at: "2026-05-14T00:00:00Z" }]);
    assert.equal(out["7d58f0cac741650a"].length, 2);
  });
});
