#!/usr/bin/env node
// Build web/src/data/byte-history.json — the build-time card_id →
// byte-history map.
//
// Sprint 4g Phase 3. Reads `data/asset-bytes-registry.jsonl` (the
// append-only log of every preserved asset's byte_sha256 + archive_key)
// and emits a card_id → ordered list of byte-history entries. Only
// cards with >1 byte_sha appear — the single-sha case is the
// uninteresting steady state and bundling it would inflate the JSON
// ~3× for no consumer (~80 multi-sha cards out of ~230 rows).
//
// Downstream consumer:
//
//   * `web/src/pages/card/[card_id].astro` — renders the
//     "edited upstream" banner above the iframe when an entry for
//     the rendered card_id is present, linking the pre-edit version
//     via /archive/<sha>.<ext> (the new worker route).
//
// Stored in `web/src/data/` (Astro SSR-imports it at build time)
// rather than `web/public/data/` because all consumption is build-
// time; there's no runtime fetch.
//
// Idempotent. Re-running with the same registry produces byte-stable
// output (sorted keys + entries) so the prebuild hook doesn't
// produce spurious dirty diffs.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const REGISTRY = resolve(here, "../../data/asset-bytes-registry.jsonl");
const EXCLUSIONS = resolve(here, "../../data/byte-history-exclusions.json");
const OUT = resolve(here, "../src/data/byte-history.json");

/**
 * Build a Set of "<card_id>|<byte_sha256>" keys from the exclusion
 * file. Entries matching a key are dropped before building the
 * card_id → entries map.
 *
 * Used to suppress registry rows the operator has determined were
 * misroutes or pipeline-evolution events (not real upstream byte
 * alterations). The registry itself stays untouched (append-only
 * invariant); exclusion is declarative and reviewable in git.
 */
export function loadExclusionKeys(exclusionDoc) {
  if (!exclusionDoc || !Array.isArray(exclusionDoc.exclusions)) return new Set();
  const keys = new Set();
  for (const [idx, ex] of exclusionDoc.exclusions.entries()) {
    if (!ex.card_id || !ex.byte_sha256) {
      // Nayru PR #79 round-7 P1: fail-closed on malformed
      // entries. The exclusions file is operator-authored
      // build-time input — a typo like `byte_sha265` would
      // otherwise silently let a misroute back into
      // byte-history.json (the URL-stability invariant catches
      // it one step downstream, but the message is confusing).
      // Throwing here names the offending entry directly.
      // Identifiers only — a valid byte_sha256 would make the
      // line ~150 chars (round-4 P2 #5).
      throw new Error(
        `[build_byte_history] exclusion entry [${idx}] is malformed — ` +
        `card_id=${JSON.stringify(ex.card_id ?? null)}, ` +
        `has_byte_sha256=${!!ex.byte_sha256}, ` +
        `keys=${JSON.stringify(Object.keys(ex))}. ` +
        `Both card_id and byte_sha256 are required. Fix the entry in ` +
        `data/byte-history-exclusions.json and re-run.`,
      );
    }
    keys.add(`${ex.card_id}|${ex.byte_sha256}`);
  }
  return keys;
}

/**
 * Pure transform: take a list of registry rows, return the card_id →
 * byte-history map for cards with >1 distinct byte_sha256.
 *
 * Entries within each card are newest-first by ``fetched_at`` so the
 * first entry is the current-pointer version.
 *
 * Rows matching an entry in ``exclusionKeys`` (Set of
 * ``"<card_id>|<byte_sha256>"`` strings) are skipped — used for
 * pipeline-evolution misroutes that aren't real upstream alterations.
 */
export function buildByteHistory(rows, exclusionKeys = new Set()) {
  const byCard = new Map();
  for (const row of rows) {
    const cardId = row.card_id;
    if (!cardId) continue;
    // Nayru PR #79 round-6 P2 #5: a row with missing byte_sha256
    // produced the exclusion key `${cardId}|undefined`, never
    // matched any operator-curated entry, and passed through
    // silently — only caught downstream by the URL-stability
    // invariant. Skip the row at the source so the registry-shape
    // assumption is enforced here.
    if (!row.byte_sha256) continue;
    if (exclusionKeys.has(`${cardId}|${row.byte_sha256}`)) continue;
    const list = byCard.get(cardId) ?? [];
    list.push({
      byte_sha256: row.byte_sha256,
      byte_size: row.byte_size,
      fetched_at: row.fetched_at,
      archive_key: row.archive_key,
      asset_filename: row.asset_filename ?? null,
    });
    byCard.set(cardId, list);
  }
  const out = {};
  // Sort card_ids so the JSON output is deterministic.
  const sortedCardIds = [...byCard.keys()].sort();
  for (const cardId of sortedCardIds) {
    const entries = byCard.get(cardId);
    // Skip single-sha cards — banner doesn't fire on them.
    if (entries.length <= 1) continue;
    // Newest-first by fetched_at. ISO-8601 strings sort lexically so
    // a plain string compare is correct.
    //
    // Comparator MUST return 0 on equal keys (Codex P2 / PR #71): the
    // prior `< ? 1 : -1` shape worked coincidentally under ES2019+
    // stable-sort but violated the sort-comparator contract — equal
    // timestamps were treated as a > b in both directions. Fall back
    // to byte_sha256 lex order as a deterministic tie-breaker when
    // two entries land at the same fetched_at (unlikely in practice
    // but pins ordering across runtimes).
    entries.sort((a, b) => {
      if (a.fetched_at !== b.fetched_at) {
        return a.fetched_at < b.fetched_at ? 1 : -1;
      }
      if (a.byte_sha256 !== b.byte_sha256) {
        return a.byte_sha256 < b.byte_sha256 ? 1 : -1;
      }
      return 0;
    });
    out[cardId] = entries.map((entry, idx) => ({
      ...entry,
      is_current: idx === 0,
    }));
  }
  return out;
}

function parseJsonl(text) {
  const rows = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    rows.push(JSON.parse(line));
  }
  return rows;
}

function main() {
  const text = readFileSync(REGISTRY, "utf-8");
  const rows = parseJsonl(text);
  let exclusionKeys = new Set();
  if (existsSync(EXCLUSIONS)) {
    let exclusionDoc;
    try {
      exclusionDoc = JSON.parse(readFileSync(EXCLUSIONS, "utf-8"));
    } catch (err) {
      // Laverna PR #79 round-3 P2: a bare SyntaxError stack from
      // a malformed exclusions file is hard to triage. Surface the
      // path + cause before re-raising so the failure message names
      // the file.
      throw new Error(
        `[build_byte_history] failed to parse exclusions file at ` +
        `${EXCLUSIONS}: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    exclusionKeys = loadExclusionKeys(exclusionDoc);
  } else if (process.env.PURSUE_ALLOW_NO_EXCLUSIONS === "1") {
    // Fresh-clone escape hatch — explicit opt-in. Operator-curated
    // exclusions are a load-bearing input (filtering 9 misroute
    // cards out of byte-history.json); a silent miss would re-
    // introduce them.
    console.warn(
      `[build_byte_history] no exclusions file at ${EXCLUSIONS}; ` +
      `processing all registry rows (PURSUE_ALLOW_NO_EXCLUSIONS=1).`,
    );
  } else {
    // Nayru PR #79 round-8 P1 #2: prior shape warned-and-continued
    // when the exclusions file was missing — accidental `git rm`
    // produced a silently-bad byte-history.json locally (URL-
    // stability invariant catches it in CI, but local builds
    // shipped misroute cards). Fail-closed at the source unless
    // PURSUE_ALLOW_NO_EXCLUSIONS=1.
    throw new Error(
      `[build_byte_history] required exclusions file missing at ` +
      `${EXCLUSIONS}. Restore data/byte-history-exclusions.json or ` +
      `set PURSUE_ALLOW_NO_EXCLUSIONS=1 to build without exclusions ` +
      `(fresh-clone / intentional removal only — the URL-stability ` +
      `invariant in build_byte_history.test.mjs will still fire).`,
    );
  }
  const history = buildByteHistory(rows, exclusionKeys);
  mkdirSync(dirname(OUT), { recursive: true });
  // Sorted-key stable encoding for byte-stable output across runs.
  // 2-space indent — same as cards-summary; the file is small (~80
  // cards × ~5 fields × 2 entries) so readability beats compactness.
  writeFileSync(OUT, JSON.stringify(history, null, 2) + "\n", "utf-8");
  const cardCount = Object.keys(history).length;
  console.log(`build_byte_history: ${cardCount} multi-sha cards → ${OUT}`);
}

// Only run main() when invoked as a script (not when imported by tests).
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
