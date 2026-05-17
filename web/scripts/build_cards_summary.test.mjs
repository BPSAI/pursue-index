// Tests for build_cards_summary.mjs — the Sprint 4b Theme F prebuild
// that emits web/public/data/cards-summary.json for CardExplorer's
// runtime fetch.
//
// We exercise the script via `child_process.execFileSync` so the test
// covers the actual entry point (no `import build` dodge). Reads from
// a tmp dir to avoid touching web/public on every test run.

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SCRIPT = resolve(here, "build_cards_summary.mjs");

/**
 * Build a minimal fixture manifest + run the script against a tmp dir.
 * The script reads from a fixed relative path
 * (../src/data/manifest.json) and writes to
 * ../public/data/cards-summary.json, so the test creates a tmp tree
 * that mirrors that layout and runs the script with cwd pointed at
 * the tmp `scripts/` dir.
 */
function runAgainstFixture(manifestObj) {
  const tmp = resolve(here, ".test-tmp-cards-summary");
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(resolve(tmp, "scripts"), { recursive: true });
  mkdirSync(resolve(tmp, "src/data"), { recursive: true });
  mkdirSync(resolve(tmp, "public/data"), { recursive: true });
  writeFileSync(
    resolve(tmp, "src/data/manifest.json"),
    JSON.stringify(manifestObj),
  );
  // Copy the real script into the tmp scripts/ so its relative paths
  // resolve against the tmp tree (the script uses ``dirname(fileURLToPath(import.meta.url))``).
  const scriptBody = readFileSync(SCRIPT, "utf8");
  writeFileSync(resolve(tmp, "scripts/build_cards_summary.mjs"), scriptBody);
  execFileSync("node", [resolve(tmp, "scripts/build_cards_summary.mjs")], {
    stdio: "pipe",
  });
  const out = JSON.parse(
    readFileSync(resolve(tmp, "public/data/cards-summary.json"), "utf8"),
  );
  rmSync(tmp, { recursive: true, force: true });
  return out;
}

test("emits one row per manifest card, in input order", () => {
  const out = runAgainstFixture({
    csv_sha256: "x".repeat(64),
    fetched_at: "2026-05-17T00:00:00Z",
    cards: [
      _stub({ card_id: "aaaaaaaaaaaaaaaa", title: "A" }),
      _stub({ card_id: "bbbbbbbbbbbbbbbb", title: "B" }),
    ],
  });
  assert.equal(out.length, 2);
  assert.equal(out[0].card_id, "aaaaaaaaaaaaaaaa");
  assert.equal(out[1].card_id, "bbbbbbbbbbbbbbbb");
});

test("drops the `raw` field even when present in the manifest", () => {
  const out = runAgainstFixture({
    csv_sha256: "x".repeat(64),
    fetched_at: "2026-05-17T00:00:00Z",
    cards: [
      _stub({
        card_id: "0000000000000000",
        title: "with-raw",
        raw: { something: "forward-compat" },
      }),
    ],
  });
  assert.equal(out.length, 1);
  assert.ok(!("raw" in out[0]), "`raw` must not leak into the runtime payload");
});

test("preserves null fields rather than coercing to undefined", () => {
  const out = runAgainstFixture({
    csv_sha256: "x".repeat(64),
    fetched_at: "2026-05-17T00:00:00Z",
    cards: [
      _stub({
        card_id: "1111111111111111",
        title: "T",
        // Every nullable field present as `null` — these must round-trip.
        asset_url: null,
        modal_image_url: null,
        original_classification: null,
      }),
    ],
  });
  assert.equal(out[0].asset_url, null);
  assert.equal(out[0].modal_image_url, null);
  assert.equal(out[0].original_classification, null);
});

test("output is minified JSON (no trailing newline, no indent)", () => {
  const tmp = resolve(here, ".test-tmp-cards-summary-min");
  rmSync(tmp, { recursive: true, force: true });
  mkdirSync(resolve(tmp, "scripts"), { recursive: true });
  mkdirSync(resolve(tmp, "src/data"), { recursive: true });
  mkdirSync(resolve(tmp, "public/data"), { recursive: true });
  writeFileSync(
    resolve(tmp, "src/data/manifest.json"),
    JSON.stringify({
      csv_sha256: "y".repeat(64),
      fetched_at: "2026-05-17T00:00:00Z",
      cards: [_stub({ card_id: "ffffffffffffffff", title: "X" })],
    }),
  );
  const scriptBody = readFileSync(SCRIPT, "utf8");
  writeFileSync(resolve(tmp, "scripts/build_cards_summary.mjs"), scriptBody);
  execFileSync("node", [resolve(tmp, "scripts/build_cards_summary.mjs")], {
    stdio: "pipe",
  });
  const text = readFileSync(
    resolve(tmp, "public/data/cards-summary.json"),
    "utf8",
  );
  rmSync(tmp, { recursive: true, force: true });
  // Byte-stable: no trailing newline, no pretty-print indent.
  assert.ok(!text.endsWith("\n"), "no trailing newline (byte-stable build)");
  assert.ok(!text.includes("\n  "), "no two-space indent (must be minified)");
});

// --- helpers ---

/** Build a minimal card row with all FIELDS present (mostly null). */
function _stub(overrides) {
  return {
    card_id: "0000000000000000",
    title: "stub",
    asset_type: "PDF",
    agency: "agency",
    release_date: null,
    incident_date: null,
    incident_location: null,
    redacted: false,
    description: null,
    asset_url: null,
    asset_filename: null,
    modal_image_url: null,
    dvids_video_id: null,
    video_title: null,
    pdf_pairing: null,
    video_pairing: null,
    image_alt_text: null,
    image_virin: null,
    original_classification: null,
    ...overrides,
  };
}
