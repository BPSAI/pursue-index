/**
 * Tests for the field-diff layer of the /diff page's pure helper module:
 * `fieldOnlyChanges` — which fields changed on cards present in both
 * snapshots, the duplicate-card_id row-pairing regression it depends on,
 * skip-set semantics pinned against `tranche.py`, absent-vs-null parity,
 * and locally-curated fields that must never read as an upstream change.
 *
 * Run with: `node --test src/components/diff-helpers-field-changes.test.ts`
 * (the project's web-side test convention — see existing
 * `atlas-helpers.test.ts` for the same pattern).
 *
 * Split out of `diff-helpers.test.ts` along its existing
 * `// --- section ---` seams — see the sibling `diff-helpers-pairing.test.ts`
 * and `diff-helpers-report.test.ts` for the rest of that file's coverage.
 * Row fixtures shared across the split live in `diff-test-fixtures.ts`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fieldOnlyChanges, DIFF_SKIP_FIELDS, LOCAL_CURATION_FIELDS } from "./diff-helpers.ts";
import { card, ea029aRows, d8e56Rows, c1c59Rows } from "./diff-test-fixtures.ts";
import type { CardMetadata } from "../data/types.ts";

// --- fieldOnlyChanges ---

test("fieldOnlyChanges: same cards same fields → 0 changes", () => {
  const a = card("aaa", "title", { agency: "FBI", incident_date: "2023-10-24" });
  const b = card("aaa", "title", { agency: "FBI", incident_date: "2023-10-24" });
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
});

test("fieldOnlyChanges: title changed on same card_id → 1 change", () => {
  const a = card("aaa", "old title");
  const b = card("aaa", "new title");
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "aaa");
  assert.ok(out[0].fields.includes("title"));
});

test("fieldOnlyChanges: multiple fields changed → all listed", () => {
  const a = card("aaa", "T1", { agency: "FBI", incident_date: "2023-10-24" });
  const b = card("aaa", "T2", { agency: "DOW", incident_date: "2023-10-24" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("title"));
  assert.ok(out[0].fields.includes("agency"));
});

test("fieldOnlyChanges: ignores cards present in only one side (those are add/remove, not field-changes)", () => {
  const a = card("aaa", "A");
  const b = card("bbb", "B");
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
});

test("fieldOnlyChanges: featured flips false→true → reported", () => {
  const a = card("aaa", "T", { featured: false });
  const b = card("aaa", "T", { featured: true });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("featured"));
});

test("fieldOnlyChanges: featured unchanged true→true → no change", () => {
  const a = card("aaa", "T", { featured: true });
  const b = card("aaa", "T", { featured: true });
  assert.equal(fieldOnlyChanges([a], [b]).length, 0);
});

test("fieldOnlyChanges: redacted absent (old snapshot) vs redacted=false → NOT a spurious change", () => {
  // `redacted` joined the boolean-normalized fields alongside `featured`,
  // so it gets the same undefined≡false treatment. Guards the (desirable)
  // behavior change to a pre-existing field — a snapshot that predates an
  // always-present `redacted` must not flood the diff against an explicit
  // false.
  const prev = card("aaa", "T");
  delete (prev as { redacted?: boolean }).redacted;
  const sameFalse = card("aaa", "T", { redacted: false });
  assert.equal(fieldOnlyChanges([prev], [sameFalse]).length, 0);

  const nowTrue = card("aaa", "T", { redacted: true });
  const out = fieldOnlyChanges([prev], [nowTrue]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("redacted"));
});

test("fieldOnlyChanges: pre-Featured snapshot (field absent) vs featured=false → NOT a spurious change", () => {
  // Snapshots taken before the Featured column lack the field entirely
  // (undefined). Comparing against a new snapshot's explicit `false`
  // must NOT register as a change, or every non-featured card would
  // flood the diff. Only a real flip to `true` should surface.
  const prev = card("aaa", "T");
  delete (prev as { featured?: boolean }).featured; // simulate old wire shape
  const sameFalse = card("aaa", "T", { featured: false });
  assert.equal(fieldOnlyChanges([prev], [sameFalse]).length, 0);

  const nowTrue = card("aaa", "T", { featured: true });
  const out = fieldOnlyChanges([prev], [nowTrue]);
  assert.equal(out.length, 1);
  assert.ok(out[0].fields.includes("featured"));
});

// --- fieldOnlyChanges + pairRowsByCardId: duplicate card_id groups ---
//
// 9 ids in the 375-card manifest carry a PDF row plus one or more VID
// rows under the SAME card_id. Keying a Map by card_id (last row wins)
// and then diffing every curr row against that one survivor compares a
// VID row to a PDF row and fabricates field changes — "a video retitled
// into a PDF". These fixtures are built from the real duplicate ids in
// snapshot 5f5698f1 (verified against data/manifests/snapshots/); the
// row builders themselves live in `diff-test-fixtures.ts` since
// `diff-helpers-pairing.test.ts`'s `pairRowsByCardId` tests use them too.

test("fieldOnlyChanges: duplicate id (ea029a05, 4 rows) diffed against itself → 0 changes", () => {
  // Regression: the id-keyed map compared the PDF row and the first two
  // VID rows against the last VID row, fabricating title changes.
  assert.deepEqual(fieldOnlyChanges(ea029aRows(), ea029aRows()), []);
});

test("fieldOnlyChanges: duplicate id (d8e5687d, 3 rows) diffed against itself → 0 changes", () => {
  assert.deepEqual(fieldOnlyChanges(d8e56Rows(), d8e56Rows()), []);
});

test("fieldOnlyChanges: duplicate id (c1c59236, 2 rows PDF+VID) diffed against itself → 0 changes", () => {
  // The live symptom: a video 'retitled into a PDF'. A PDF row must only
  // ever be compared to a PDF row, so self-diff is empty.
  assert.deepEqual(fieldOnlyChanges(c1c59Rows(), c1c59Rows()), []);
});

test("fieldOnlyChanges: PDF row is only compared to PDF row, never to the VID row", () => {
  // Change ONLY the PDF row's title on the curr side. The result must
  // report a title change and NOTHING else — in particular never
  // asset_type or video_title, which would leak in if PDF were paired
  // with VID.
  const prev = c1c59Rows();
  const curr = c1c59Rows();
  curr[0] = { ...curr[0], title: "DOW-UAP-D010, Mission Report, Middle East, May 2022 (rev)" };
  const out = fieldOnlyChanges(prev, curr);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "c1c59236394f7b14");
  assert.deepEqual(out[0].fields, ["title"]);
});

test("fieldOnlyChanges: a change on one of several identical-key VID rows is paired positionally", () => {
  // The 3 ea029a05 VID rows share an identical pairing key. Changing the
  // middle VID row's incident_location must surface incident_location
  // (and nothing spurious like title, which stays put under positional
  // pairing PR032↔PR032).
  const prev = ea029aRows();
  const curr = ea029aRows();
  curr[2] = { ...curr[2], incident_location: "Türkiye" };
  const out = fieldOnlyChanges(prev, curr);
  assert.equal(out.length, 1);
  assert.equal(out[0].card_id, "ea029a05470b8f4e");
  assert.deepEqual(out[0].fields, ["incident_location"]);
});

// --- T47.4: skip-set semantics (was a 15-field allowlist) ----------------
//
// The allowlist silently dropped 107 real upstream changes across the
// corpus history: pdf_pairing (86), video_pairing (17), dvids_video_id
// (4) — never in `_COMPARED_FIELDS`, so a change to any of them rendered
// as no change at all on this page. Skip-set semantics compare
// everything except an explicit skip set, so a field is surfaced unless
// someone deliberately excludes it.

/**
 * Read a module-level `NAME = { "a", "b", ... }` set literal out of
 * `tranche.py`. Both exclusion sets are pinned this way rather than by
 * duplicating their members here, so adding a field on the Python side
 * without adding it on this one fails loudly instead of silently making
 * the receipt and the page describe a tranche differently.
 */
function pyFieldSet(pySrc: string, name: string): Set<string> {
  const match = new RegExp(`^${name}\\s*=\\s*\\{([^}]*)\\}`, "m").exec(pySrc);
  assert.ok(match, `tranche.py must still define ${name} as a module-level set literal`);
  const fields = new Set(Array.from(match[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]));
  assert.ok(fields.size > 0, `regex must actually find quoted field names in ${name}`);
  return fields;
}

function tranchePySource(): string {
  return readFileSync(new URL("../../../src/pursue_index/tranche.py", import.meta.url), "utf-8");
}

test("fieldOnlyChanges: DIFF_SKIP_FIELDS matches tranche.py's DIFF_SKIP_FIELDS exactly", () => {
  assert.deepEqual(
    DIFF_SKIP_FIELDS,
    pyFieldSet(tranchePySource(), "DIFF_SKIP_FIELDS"),
    "the site's skip set has drifted from tranche.py's — keep them identical",
  );
});

test("fieldOnlyChanges: LOCAL_CURATION_FIELDS matches tranche.py's LOCAL_CURATION_FIELDS exactly", () => {
  assert.deepEqual(
    LOCAL_CURATION_FIELDS,
    pyFieldSet(tranchePySource(), "LOCAL_CURATION_FIELDS"),
    "the site's curation-field set has drifted from tranche.py's — keep them identical",
  );
});

test("fieldOnlyChanges: the two exclusion sets stay disjoint and separately named", () => {
  // They are excluded for different reasons (pairing key + volatile
  // upstream metadata vs. our own editorial writes), and the receipt's
  // rationale comments are keyed to that split. A field drifting into
  // both would make either set's stated reason untrue for it.
  for (const f of LOCAL_CURATION_FIELDS) {
    assert.ok(!DIFF_SKIP_FIELDS.has(f), `${f} belongs to exactly one exclusion set`);
  }
  assert.ok(LOCAL_CURATION_FIELDS.size > 0 && DIFF_SKIP_FIELDS.size > 0);
});

test("fieldOnlyChanges: pdf_pairing change surfaces (previously silently dropped)", () => {
  const a = card("aaa", "T", { pdf_pairing: null });
  const b = card("aaa", "T", { pdf_pairing: "some-video-id" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["pdf_pairing"]);
});

test("fieldOnlyChanges: video_pairing change surfaces (previously silently dropped)", () => {
  const a = card("aaa", "T", { video_pairing: null });
  const b = card("aaa", "T", { video_pairing: "some-pdf-id" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["video_pairing"]);
});

test("fieldOnlyChanges: dvids_video_id change on a non-keying pair surfaces", () => {
  // dvids_video_id is also a row-pairing key (row-pairing.ts), but a
  // solo PDF row (no video_title siblings) still bucket-pairs 1:1 across
  // snapshots, so a dvids_video_id mutation reaches the field diff here
  // rather than only showing up as an add/remove of an unpaired row.
  const a = card("aaa", "T", { dvids_video_id: "111" });
  const b = card("aaa", "T", { dvids_video_id: "222" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["dvids_video_id"]);
});

// --- absent-vs-null parity with tranche.py (P0, post-T47.4) --------------
//
// `field_diff` reads both sides with `dict.get()`, so a key that is absent
// on one side and explicitly `null` on the other compares EQUAL. The
// union-of-keys loop here compared the raw values, and `undefined !== null`,
// so every snapshot schema addition — a manifest rebuilt after a new column
// exists carries it as `null` on rows with no value, while the older
// snapshot simply lacks the key — fabricated one "change" per row per new
// column on every historical pair.

test("fieldOnlyChanges: a field absent on prev and explicitly null on curr is not a change", () => {
  const a = card("aaa", "T");
  delete (a as Record<string, unknown>).original_classification;
  const b = card("aaa", "T", { original_classification: null });
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: a field explicitly null on prev and absent on curr is not a change", () => {
  const a = card("aaa", "T", { original_classification: null });
  const b = card("aaa", "T");
  delete (b as Record<string, unknown>).original_classification;
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: a field absent on prev and given a real value on curr is still a change", () => {
  // The absent==null rule must not swallow a genuine introduction of a
  // value — only the null/undefined serialization difference.
  const a = card("aaa", "T");
  delete (a as Record<string, unknown>).original_classification;
  const b = card("aaa", "T", { original_classification: "SECRET" });
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["original_classification"]);
});

// --- locally-curated fields are not upstream change (P0, post-T47.4) -----
//
// /diff describes what war.gov edited. The display_date_* family and
// `manifest_incident_date_raw` are written by OUR curation pipeline, so a
// snapshot taken after a curation pass differs from one taken before on
// every card we touched — hundreds of entries on a page whose whole claim
// is that it reports government edits.

test("fieldOnlyChanges: a display_date curated by us is not reported as an upstream change", () => {
  const a = card("aaa", "T", { display_date: null } as Partial<CardMetadata>);
  const b = card("aaa", "T", { display_date: "2023-10-24" } as Partial<CardMetadata>);
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});

test("fieldOnlyChanges: every LOCAL_CURATION_FIELDS entry is excluded", () => {
  for (const field of LOCAL_CURATION_FIELDS) {
    const a = card("aaa", "T", { [field]: null } as Partial<CardMetadata>);
    const b = card("aaa", "T", { [field]: "curated-value" } as Partial<CardMetadata>);
    assert.deepEqual(fieldOnlyChanges([a], [b]), [], `${field} must not be reported`);
  }
});

test("fieldOnlyChanges: a real upstream edit still reports alongside a curation field", () => {
  const a = card("aaa", "T", { display_date: null, incident_location: "Iraq" } as Partial<CardMetadata>);
  const b = card("aaa", "T", {
    display_date: "2023-10-24",
    incident_location: "Syria",
  } as Partial<CardMetadata>);
  const out = fieldOnlyChanges([a], [b]);
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].fields, ["incident_location"]);
});

test("fieldOnlyChanges: card_id and raw are never reported even though they'd differ if compared", () => {
  // card_id is the pairing key so it can never itself differ within a
  // pair; this pins that the skip set still excludes it explicitly
  // rather than relying on that incidental fact.
  const a = card("aaa", "T");
  const b = card("aaa", "T");
  assert.deepEqual(fieldOnlyChanges([a], [b]), []);
});
