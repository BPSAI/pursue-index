/**
 * Cross-language agreement for row pairing.
 *
 * The /diff page (TypeScript) and the tranche receipt generator
 * (Python) pair manifest rows independently. If the two ever disagree,
 * the published diff and the committed receipt describe the same tranche
 * differently. Both sides read the SAME case file —
 * `tests/fixtures/row_pairing_cases.json` — so agreement is a property
 * of the fixture rather than of two hand-maintained copies of the same
 * literals. The Python half lives in `tests/unit/test_row_pairing_fixture.py`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pairRowsByCardId } from "./row-pairing.ts";
import type { CardMetadata } from "../data/types.ts";

interface PairingCase {
  name: string;
  prev: CardMetadata[];
  curr: CardMetadata[];
  expected_pairs: [number, number][];
  expected_unpaired: Array<{ side: "prev" | "curr"; index: number }>;
}

const CASES: PairingCase[] = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/row_pairing_cases.json", import.meta.url), "utf-8"),
).cases;

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
