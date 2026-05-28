// Tests for build_byte_history.mjs.
//
// Sprint 4g Phase 3. The script reads data/asset-bytes-registry.jsonl
// and emits a card_id → ordered byte-history map for the card-detail
// banner + the /altered page. Only cards with >1 byte_sha appear in
// the output — the on-page banner only fires on those, and bundling
// the single-sha cards would inflate the JSON ~3× for no consumer.

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { buildByteHistory, loadExclusionKeys } from "./build_byte_history.mjs";

const _here = dirname(fileURLToPath(import.meta.url));
const REGISTRY_PATH = resolve(_here, "../../data/asset-bytes-registry.jsonl");
const EXCLUSIONS_PATH = resolve(_here, "../../data/byte-history-exclusions.json");

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

  test("comparator returns 0 on equal keys (sort contract)", () => {
    // Codex P2 / PR #71: the prior comparator `< ? 1 : -1` never
    // returned 0. ES2019+ stable-sort masked the contract violation,
    // but the tie-breaker still needs to be deterministic so two
    // entries at the same fetched_at don't flip across runtimes /
    // engines. byte_sha256 lex order is the tie-breaker.
    const sameTs = "2026-05-12T00:00:00Z";
    const rows = [
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: sameTs, archive_key: "archive/b.pdf", asset_filename: "f.pdf" },
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: sameTs, archive_key: "archive/a.pdf", asset_filename: "f.pdf" },
    ];
    const out = buildByteHistory(rows);
    // b > a lex-wise → b comes first; a (lex-smaller) comes second.
    assert.equal(out.x[0].byte_sha256, "b".repeat(64));
    assert.equal(out.x[1].byte_sha256, "a".repeat(64));
    assert.equal(out.x[0].is_current, true);
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

describe("loadExclusionKeys + exclusion filtering", () => {
  test("loadExclusionKeys produces card_id|byte_sha256 keys", () => {
    const doc = {
      version: 1,
      exclusions: [
        { card_id: "abc", byte_sha256: "f".repeat(64) },
        { card_id: "def", byte_sha256: "e".repeat(64) },
      ],
    };
    const keys = loadExclusionKeys(doc);
    assert.equal(keys.size, 2);
    assert.ok(keys.has(`abc|${"f".repeat(64)}`));
    assert.ok(keys.has(`def|${"e".repeat(64)}`));
  });

  test("loadExclusionKeys handles missing or malformed input", () => {
    assert.equal(loadExclusionKeys(null).size, 0);
    assert.equal(loadExclusionKeys({}).size, 0);
    assert.equal(loadExclusionKeys({ exclusions: "not-an-array" }).size, 0);
  });

  test("buildByteHistory drops excluded entries", () => {
    const rows = [
      { card_id: "x", byte_sha256: "a".repeat(64), byte_size: 100, fetched_at: "2026-05-11T00:00:00Z", archive_key: "archive/a.mp4", asset_filename: "v.mp4" },
      { card_id: "x", byte_sha256: "b".repeat(64), byte_size: 200, fetched_at: "2026-05-12T00:00:00Z", archive_key: "archive/b.pdf", asset_filename: "p.pdf" },
    ];
    // Without exclusion: card "x" is multi-sha, appears.
    assert.ok(buildByteHistory(rows).x);
    // With the mp4 excluded: card "x" becomes single-sha → drops out.
    const keys = new Set([`x|${"a".repeat(64)}`]);
    const out = buildByteHistory(rows, keys);
    assert.ok(!out.x, "card with only one remaining entry should drop out of multi-sha map");
  });
});

describe("registry invariant — URL-stability across non-excluded entries", () => {
  // This is the recurrence-detector for the 2026-05-11/12 pipeline-
  // evolution misroute event (see opsec finding
  // 2026-05-28-pipeline-byte-misroute-9-cards.md). Every card_id in
  // the registry should have exactly one distinct asset_url across all
  // non-excluded fetches. If a future event registers a different URL
  // under an existing card_id, this test fails before anything ships
  // and the operator decides whether to add an exclusion entry or
  // investigate the pipeline regression.
  test("every card_id in the live registry has one distinct asset_url (after exclusions)", () => {
    if (!existsSync(REGISTRY_PATH)) {
      // Repo may not have the registry checked in (e.g. fresh clone
      // without data/). Skip rather than fail in that case — the
      // invariant only matters when the registry exists.
      return;
    }
    const exclusionKeys = existsSync(EXCLUSIONS_PATH)
      ? loadExclusionKeys(JSON.parse(readFileSync(EXCLUSIONS_PATH, "utf-8")))
      : new Set();
    const text = readFileSync(REGISTRY_PATH, "utf-8");
    const urlsByCard = new Map();
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      const row = JSON.parse(line);
      const cid = row.card_id;
      if (!cid) continue;
      if (exclusionKeys.has(`${cid}|${row.byte_sha256}`)) continue;
      const set = urlsByCard.get(cid) ?? new Set();
      set.add(row.asset_url);
      urlsByCard.set(cid, set);
    }
    const offenders = [];
    for (const [cid, urls] of urlsByCard) {
      if (urls.size > 1) {
        offenders.push({ card_id: cid, urls: [...urls] });
      }
    }
    assert.equal(
      offenders.length,
      0,
      `Cards with multiple asset_urls (after exclusions): ${JSON.stringify(offenders, null, 2)}\n\n` +
      `If this fires for a new card, the pipeline registered a different URL under an existing card_id. ` +
      `Either add an entry to data/byte-history-exclusions.json (with operator justification + opsec_ref) ` +
      `or investigate the pipeline. See findings/2026-05-28-pipeline-byte-misroute-9-cards.md in pursue-opsec for the prior incident.`
    );
  });

  test("every exclusion entry corresponds to a real registry row (no stale exclusions)", () => {
    if (!existsSync(EXCLUSIONS_PATH) || !existsSync(REGISTRY_PATH)) return;
    const doc = JSON.parse(readFileSync(EXCLUSIONS_PATH, "utf-8"));
    const registryKeys = new Set();
    const text = readFileSync(REGISTRY_PATH, "utf-8");
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      const row = JSON.parse(line);
      if (row.card_id && row.byte_sha256) {
        registryKeys.add(`${row.card_id}|${row.byte_sha256}`);
      }
    }
    const stale = [];
    for (const ex of doc.exclusions || []) {
      const key = `${ex.card_id}|${ex.byte_sha256}`;
      if (!registryKeys.has(key)) {
        stale.push(ex);
      }
    }
    assert.equal(
      stale.length,
      0,
      `Stale exclusion entries (no matching registry row): ${JSON.stringify(stale, null, 2)}`
    );
  });
});
