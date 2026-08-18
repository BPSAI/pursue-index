#!/usr/bin/env node
// Build web/public/data/cards-summary.json — the runtime fetch payload
// for CardExplorer.
//
// Before this script, the homepage inlined the
// full 158-card serialized props of <CardExplorer client:visible> in
// dist/index.html as a 676 KB HTML-encoded JSON blob. Lighthouse
// flagged "Avoid an excessive DOM size" as the headline Best
// Practices finding because every astro-island prop is HTML-escaped
// and lives in a single <astro-island> element. Result: a 695 KB
// HTML payload for a page whose meaningful content is ~30 KB.
//
// New shape:
//
//   1. This prebuild script emits a minified JSON file at
//      web/public/data/cards-summary.json (~253 KB raw,
//      gzip ~50 KB on the wire).
//   2. <CardExplorer client:visible> no longer receives `cards` as a
//      prop — it fetches /data/cards-summary.json on hydration. CF
//      edge cache handles the static file under the existing
//      Cache-Control rule for /data/*.json.
//   3. The HTML blob drops by ~440 KB; the JSON payload moves from
//      "every-character-HTML-encoded once" to "served as-is, gzipped
//      once, edge-cached".
//
// Input: web/src/data/manifest.json (the build-time manifest snapshot
// that lib/release.ts also reads).
// Output: web/public/data/cards-summary.json (the runtime fetch).
//
// Idempotent. Re-running with the same manifest produces byte-stable
// output (minified, no trailing newline) so the prebuild hook doesn't
// produce spurious dirty diffs.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const MANIFEST = resolve(here, "../src/data/manifest.json");
const OUT = resolve(here, "../public/data/cards-summary.json");

// Explicit allowlist of fields CardExplorer uses.
// Drops `raw` (always empty per types.ts comment) and keeps the bundle
// lean. If a new field is added to types.ts and CardExplorer needs it,
// add it here too — the build will silently exclude unknown fields,
// which is the right failure mode for forward-compat.
const FIELDS = [
  "card_id",
  "title",
  "asset_type",
  "agency",
  "release_date",
  "incident_date",
  "incident_location",
  "redacted",
  "description",
  "asset_url",
  "asset_filename",
  "modal_image_url",
  "dvids_video_id",
  "video_title",
  "pdf_pairing",
  "video_pairing",
  "image_alt_text",
  "image_virin",
  "original_classification",
];

function slimCard(card) {
  const out = {};
  for (const k of FIELDS) {
    // Preserve nulls / falsey strings exactly — the React types pin
    // each field as `T | null`, and dropping `undefined` to `null`
    // keeps the type contract on the client side. The `??` shorthand
    // preserves explicit `null` and only substitutes
    // when the value is missing or `undefined`. Empty strings, `0`,
    // and `false` round-trip unchanged.
    out[k] = card[k] ?? null;
  }
  return out;
}

const raw = readFileSync(MANIFEST, "utf8");
const manifest = JSON.parse(raw);

// Schema sanity: a malformed manifest must abort the
// build with a clear, named error rather than crashing somewhere
// downstream with ``TypeError: manifest.cards.map is not a function``.
// The most likely shapes for accidental breakage are ``null``
// (jq-filter-misses-empty), ``{}`` (whole-object passthrough bug),
// or ``undefined`` (key typo). All of those fail this check.
if (!Array.isArray(manifest.cards)) {
  console.error(
    `[build_cards_summary] manifest.cards is not an array (got ${
      manifest.cards === null ? "null" : typeof manifest.cards
    }); aborting`,
  );
  process.exit(1);
}

const cards = manifest.cards.map(slimCard);

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(cards));
console.log(
  `wrote ${OUT.replace(resolve(here, ".."), "web")} (${cards.length} cards)`,
);
