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

// PURSUE_STRICT_INVARIANTS=1 turns the file-missing skip path into a
// hard fail. The release-pipeline CI runs with this set so a CI
// misconfig that strips data/asset-bytes-registry.jsonl can't silently
// pass the invariant gates that depend on it. Local + fresh-clone
// runs (no env var) still skip cleanly. Nayru PR #79 round-2 P1-1 +
// Vaivora P2-6.
const STRICT_INVARIANTS = process.env.PURSUE_STRICT_INVARIANTS === "1";

function _missingDataSkip(label, path) {
  if (STRICT_INVARIANTS) {
    throw new Error(
      `[strict-invariants] required data file missing at ${path} — ` +
      `${label} cannot run. Set PURSUE_STRICT_INVARIANTS=0 (or unset) ` +
      `for fresh-clone runs that legitimately don't have data/.`,
    );
  }
  console.warn(
    `[byte-history.test] ${label}: data file missing at ${path} — ` +
    `skipping. Set PURSUE_STRICT_INVARIANTS=1 to fail-loud in CI.`,
  );
}

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
      _missingDataSkip("URL-stability invariant", REGISTRY_PATH);
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
    // Nayru PR #79 round-3 P2: name the actually-missing path so
    // CI diagnostics don't claim the wrong file when only one of
    // the two is absent.
    if (!existsSync(EXCLUSIONS_PATH)) {
      _missingDataSkip("stale-exclusion check", EXCLUSIONS_PATH);
      return;
    }
    if (!existsSync(REGISTRY_PATH)) {
      _missingDataSkip("stale-exclusion check", REGISTRY_PATH);
      return;
    }
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

const BUNDLE_PATH = resolve(_here, "../src/data/verdict-bundle.json");
const BYTE_HISTORY_PATH = resolve(_here, "../src/data/byte-history.json");
const MANIFEST_PATH = resolve(_here, "../src/data/manifest.json");

describe("verdict-bundle ↔ byte-history symmetric drift check", () => {
  // Vaivora PR #79 round-2 P2-7: the prior tests guarded
  // exclusions vs registry. The complementary direction — bundle
  // verdicts vs byte-history map — wasn't asserted. If a future
  // operator drops a multi-sha card from byte-history without
  // also pruning its verdict, the listing's row count and the
  // bundle's stats.verdicts_emitted silently desync. Today both
  // sides match at 71/71; this test pins that contract.

  test("every verdict in the bundle has a matching byte-history entry", () => {
    if (!existsSync(BUNDLE_PATH) || !existsSync(BYTE_HISTORY_PATH)) {
      _missingDataSkip("bundle/byte-history symmetry", BUNDLE_PATH);
      return;
    }
    const bundle = JSON.parse(readFileSync(BUNDLE_PATH, "utf-8"));
    const byteHistory = JSON.parse(readFileSync(BYTE_HISTORY_PATH, "utf-8"));
    const bhKeys = new Set(Object.keys(byteHistory));
    const orphanVerdicts = [];
    for (const cardId of Object.keys(bundle.verdicts ?? {})) {
      if (!bhKeys.has(cardId)) {
        orphanVerdicts.push(cardId);
      }
    }
    assert.equal(
      orphanVerdicts.length,
      0,
      `Bundle verdicts with no matching byte-history entry: ${JSON.stringify(orphanVerdicts)}. ` +
      `These cards would render in stats but not in the table — either restore the byte-history ` +
      `entries (preferred) or remove the verdicts from the bundle (only if the cards genuinely ` +
      `lost their multi-sha status).`
    );
  });

  test("every byte-history entry has a matching verdict in the bundle", () => {
    if (!existsSync(BUNDLE_PATH) || !existsSync(BYTE_HISTORY_PATH)) {
      _missingDataSkip("byte-history/bundle symmetry", BUNDLE_PATH);
      return;
    }
    const bundle = JSON.parse(readFileSync(BUNDLE_PATH, "utf-8"));
    const byteHistory = JSON.parse(readFileSync(BYTE_HISTORY_PATH, "utf-8"));
    const verdictKeys = new Set(Object.keys(bundle.verdicts ?? {}));
    // Unverdicted byte-history entries are legal — they render as
    // "(unverified)" on /altered/. We assert this only counts and
    // labels stay consistent; orphan-bundle is the load-bearing
    // direction. (Kept as a soft check so a sudden "unverified"
    // jump shows up in CI logs even though it doesn't fail.)
    const unverdicted = [];
    for (const cardId of Object.keys(byteHistory)) {
      if (!verdictKeys.has(cardId)) unverdicted.push(cardId);
    }
    if (unverdicted.length > 0) {
      console.warn(
        `[byte-history.test] ${unverdicted.length} byte-history cards have no verdict ` +
        `(will render as "(unverified)" on /altered/): ${unverdicted.slice(0, 5).join(", ")}` +
        `${unverdicted.length > 5 ? "..." : ""}`,
      );
    }
    // Always-pass assertion so the test serves as a count tripwire
    // rather than a gate.
    assert.ok(true);
  });
});

describe("byte-history ⊆ manifest invariant", () => {
  // Vaivora PR #79 round-3 P2 #6: altered/[card_id].astro generates
  // routes from byteHistory keys; card/[card_id].astro generates
  // from manifest. If a registry row ever points at a card that's
  // since been removed from the manifest, /altered/<id>/ would
  // render but the "see /card/<id>/" cross-link would 404. Pin the
  // invariant so a future drift fails CI loudly.
  test("every byte-history card_id is a current manifest card", () => {
    if (!existsSync(BYTE_HISTORY_PATH)) {
      _missingDataSkip("byte-history/manifest invariant", BYTE_HISTORY_PATH);
      return;
    }
    if (!existsSync(MANIFEST_PATH)) {
      _missingDataSkip("byte-history/manifest invariant", MANIFEST_PATH);
      return;
    }
    const byteHistory = JSON.parse(readFileSync(BYTE_HISTORY_PATH, "utf-8"));
    const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf-8"));
    const manifestIds = new Set(
      (manifest.cards ?? []).map((c) => c.card_id).filter(Boolean),
    );
    const orphans = [];
    for (const cardId of Object.keys(byteHistory)) {
      if (!manifestIds.has(cardId)) orphans.push(cardId);
    }
    assert.equal(
      orphans.length,
      0,
      `byte-history.json has ${orphans.length} card_id(s) not in manifest.json: ` +
      `${JSON.stringify(orphans)}. The /altered/<card_id>/ detail page renders ` +
      `for these but its "see /card/<card_id>/" cross-link 404s. Either: (a) ` +
      `restore the manifest entries (preferred if the cards are still ` +
      `upstream-published), (b) add an exclusion to ` +
      `data/byte-history-exclusions.json (if the registry rows are misroutes), ` +
      `or (c) prune the registry rows (rare — invokes append-only break).`,
    );
  });
});
