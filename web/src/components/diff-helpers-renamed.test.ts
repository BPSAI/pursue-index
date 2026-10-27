/**
 * Tests for the /diff RENAMED row's byte-change evidence (R7C.13):
 * the optional `old_byte_sha256` / `new_byte_sha256` / `change_nature`
 * alias fields thread through `resolveAliases` → `diffWithAliases`, and
 * `describeRenamedRow` decides what the row shows — the nature of change
 * plus short shas when known, and exactly today's row when not.
 *
 * Run with: `node --test src/components/diff-helpers-renamed.test.ts`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { diffWithAliases, resolveAliases } from "./diff-helpers.ts";
import { describeRenamedRow } from "./diff-renamed.ts";
import { card } from "./diff-test-fixtures.ts";
import type { AliasEntry } from "../data/types.ts";

const OLD_SHA = "d52431b354af55b1e86cb454e61fd61993af3b023a38f2d9e014a9c9d18d16b4";
const NEW_SHA = "ca9563779824e306f11393612fe6503f39877c6d5be03e77c875e928ee116b54";

function alias(old_card_id: string, new_card_id: string, extras: Partial<AliasEntry> = {}): AliasEntry {
  return { old_card_id, new_card_id, method: "operator_manual", established: "2026-10-24T00:00:00Z", ...extras };
}

const D042 = alias("a0f6663169c21caf", "ff3939f95d878062", {
  old_byte_sha256: OLD_SHA,
  new_byte_sha256: NEW_SHA,
  change_nature: "metadata-only",
});

test("resolveAliases: carries the byte-change evidence of the alias row", () => {
  const a = resolveAliases([D042])["a0f6663169c21caf"];
  assert.equal(a.terminal, "ff3939f95d878062");
  assert.equal(a.changeNature, "metadata-only");
  assert.equal(a.oldByteSha256, OLD_SHA);
  assert.equal(a.newByteSha256, NEW_SHA);
});

const SHA_C = "c".repeat(64);

test("resolveAliases: a chain with a non-metadata hop never shows one hop's evidence as another's", () => {
  const map = resolveAliases([D042, alias("ff3939f95d878062", "1111222233334444", { method: "byte_collision" })]);
  const a = map["a0f6663169c21caf"];
  assert.equal(a.terminal, "1111222233334444");
  assert.equal(a.method, "operator_manual");
  assert.equal(a.changeNature, "chain, see hops");
  assert.equal(a.oldByteSha256, undefined);
  assert.equal(a.newByteSha256, undefined);
  assert.deepEqual(
    a.hops?.map((h) => [h.from, h.to, h.changeNature ?? null]),
    [["a0f6663169c21caf", "ff3939f95d878062", "metadata-only"], ["ff3939f95d878062", "1111222233334444", null]],
  );
  assert.equal(map["ff3939f95d878062"].changeNature, undefined);
});

test("resolveAliases: an all-metadata-only chain spans first old sha to last new sha", () => {
  const hop2 = alias("ff3939f95d878062", "1111222233334444", {
    old_byte_sha256: NEW_SHA, new_byte_sha256: SHA_C, change_nature: "metadata-only",
  });
  const a = resolveAliases([D042, hop2])["a0f6663169c21caf"];
  assert.equal(a.changeNature, "metadata-only");
  assert.equal(a.oldByteSha256, OLD_SHA);
  assert.equal(a.newByteSha256, SHA_C);
});

test("resolveAliases: a single hop is unchanged by the chain rule", () => {
  const a = resolveAliases([D042])["a0f6663169c21caf"];
  assert.equal(a.changeNature, "metadata-only");
  assert.equal(a.hops, undefined);
});

test("diffWithAliases: the renamed entry carries the evidence", () => {
  const prev = [card("a0f6663169c21caf", "D42")];
  const curr = [card("ff3939f95d878062", "DOW-UAP-D042")];
  const [r] = diffWithAliases(prev, curr, resolveAliases([D042])).renamed;
  assert.equal(r.changeNature, "metadata-only");
  assert.equal(r.oldByteSha256, OLD_SHA);
  assert.equal(r.newByteSha256, NEW_SHA);
});

test("describeRenamedRow: metadata-only with both shas → nature + 12-char short shas", () => {
  const d = describeRenamedRow({
    method: "operator_manual",
    changeNature: "metadata-only",
    oldByteSha256: OLD_SHA,
    newByteSha256: NEW_SHA,
  });
  assert.deepEqual(d, {
    method: "operator_manual",
    changeNature: "metadata-only",
    shaChange: { short: "d52431b354af → ca9563779824", full: `${OLD_SHA} → ${NEW_SHA}` },
  });
});

test("describeRenamedRow: no evidence → exactly today's row (method only)", () => {
  assert.deepEqual(describeRenamedRow({ method: "byte_collision" }), {
    method: "byte_collision",
    changeNature: null,
    shaChange: null,
  });
});

test("describeRenamedRow: one known sha shows the other side as unknown", () => {
  const d = describeRenamedRow({ method: "metadata-only-resave", newByteSha256: NEW_SHA });
  assert.equal(d.changeNature, null);
  assert.deepEqual(d.shaChange, { short: "? → ca9563779824", full: `? → ${NEW_SHA}` });
});
