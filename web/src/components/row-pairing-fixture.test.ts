/**
 * Cross-language agreement for row pairing and change reporting.
 *
 * The /diff page (TypeScript) and the tranche receipt generator
 * (Python) pair manifest rows — and decide which changed fields to
 * report — independently. If the two ever disagree, the published diff
 * and the committed receipt describe the same tranche differently. Both
 * sides read the SAME case file — `tests/fixtures/row_pairing_cases.json`
 * — so agreement is a property of the fixture rather than of two
 * hand-maintained copies of the same literals. The Python half lives in
 * `tests/unit/test_row_pairing_fixture.py`.
 *
 * `cases` pins pairing; `reporting_cases` pins what each side reports
 * once two rows are paired. Pairing agreement alone is not enough: a
 * field one side compares and the other does not is a mutation that
 * reaches the committed receipt while this page renders nothing for it.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pairRowsByCardId } from "./row-pairing.ts";
import { fieldOnlyChanges } from "./diff-helpers.ts";
import type { CardMetadata } from "../data/types.ts";

interface PairingCase {
  name: string;
  prev: CardMetadata[];
  curr: CardMetadata[];
  expected_pairs: [number, number][];
  expected_unpaired: Array<{ side: "prev" | "curr"; index: number }>;
}

interface ReportingCase {
  name: string;
  prev: CardMetadata[];
  curr: CardMetadata[];
  expected_changed_fields: Record<string, string[]>;
}

const FIXTURE = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/row_pairing_cases.json", import.meta.url), "utf-8"),
);
const CASES: PairingCase[] = FIXTURE.cases;
const REPORTING_CASES: ReportingCase[] = FIXTURE.reporting_cases;

/** Sorted comparison — pairing must not depend on iteration order. */
function sortPairs(pairs: [number, number][]): string[] {
  return pairs.map(([a, b]) => `${a}->${b}`).sort();
}

function sortUnpaired(rows: Array<{ side: string; index: number }>): string[] {
  return rows.map((r) => `${r.side}:${r.index}`).sort();
}

test("row_pairing_cases.json: fixture is non-trivial", () => {
  assert.ok(CASES.length >= 8, "fixture must cover the pairing rules");
  for (const c of CASES) assert.ok(c.name, "every case must be named");
});

for (const c of CASES) {
  test(`row pairing fixture: ${c.name}`, () => {
    const { pairs, unpaired } = pairRowsByCardId(c.prev, c.curr);
    const actualPairs = pairs.map(
      (p) => [c.prev.indexOf(p.prev), c.curr.indexOf(p.curr)] as [number, number],
    );
    for (const [a, b] of actualPairs) {
      assert.ok(a >= 0 && b >= 0, "pairs must reference the original row objects");
    }
    assert.deepEqual(sortPairs(actualPairs), sortPairs(c.expected_pairs));

    const actualUnpaired = unpaired.map((u) => ({
      side: u.side,
      index: u.side === "prev" ? c.prev.indexOf(u.row) : c.curr.indexOf(u.row),
    }));
    for (const u of actualUnpaired) {
      assert.ok(u.index >= 0, "unpaired rows must reference the original row objects");
    }
    assert.deepEqual(sortUnpaired(actualUnpaired), sortUnpaired(c.expected_unpaired));
  });
}

/** {card_id: sorted changed field names} for a whole snapshot pair. */
function reportedFields(prev: CardMetadata[], curr: CardMetadata[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const change of fieldOnlyChanges(prev, curr)) {
    if (change.fields.length > 0) out[change.card_id] = [...change.fields].sort();
  }
  return out;
}

test("row_pairing_cases.json: reporting cases are present", () => {
  assert.ok(REPORTING_CASES.length >= 3, "fixture must pin reporting, not only pairing");
  for (const c of REPORTING_CASES) assert.ok(c.name, "every reporting case must be named");
});

for (const c of REPORTING_CASES) {
  test(`row reporting fixture: ${c.name}`, () => {
    const expected: Record<string, string[]> = {};
    for (const [cardId, fields] of Object.entries(c.expected_changed_fields)) {
      expected[cardId] = [...fields].sort();
    }
    assert.deepEqual(reportedFields(c.prev, c.curr), expected);
  });
}
