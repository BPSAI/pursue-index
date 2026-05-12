// Tests for the card-alias resolver.
//
// Background: when upstream renames a card, our scripts/r2_pin_removed
// + tranche_diff stack records the old → new card_id mapping in
// data/card-aliases.json (also deployed to web/public/data/ so it's
// served from the static-assets binding). The worker's job is to
// route `/card/<old_id>` requests to `/card/<new_id>` via 301, and
// stamp `X-Pursue-Aliased-To` on `/pdf/<old_id>.pdf` responses so
// downstream consumers (citations, indexers, archives) can follow
// the rename chain without losing the original handle.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  buildAliasIndex,
  parseCardPath,
  parsePdfPath,
  resolveAlias,
  tryHandleCardAlias,
} from "../aliases.js";

const OLD_ID = "aa3097b4c549a67a";
const NEW_ID = "9e2c2621d67dde12";
const ANOTHER_OLD = "13f86e95aed52840";
const ANOTHER_NEW = "ffffaaaa00001111";

const SAMPLE = {
  aliases: [
    {
      old_card_id: OLD_ID,
      new_card_id: NEW_ID,
      byte_sha256: "aba3ec3b...",
      established: "2026-05-12T19:30:00Z",
      method: "byte_collision",
    },
  ],
};

describe("buildAliasIndex", () => {
  test("indexes a single alias by old_card_id", () => {
    const idx = buildAliasIndex(SAMPLE);
    const row = idx.get(OLD_ID);
    assert.ok(row, "expected alias entry for OLD_ID");
    assert.equal(row.new_card_id, NEW_ID);
  });

  test("returns empty index on missing input", () => {
    assert.equal(buildAliasIndex(null).size, 0);
    assert.equal(buildAliasIndex({}).size, 0);
    assert.equal(buildAliasIndex({ aliases: [] }).size, 0);
  });

  test("later entry wins per old_card_id (operator override of byte_collision)", () => {
    const idx = buildAliasIndex({
      aliases: [
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-01-01", method: "byte_collision" },
        { old_card_id: OLD_ID, new_card_id: ANOTHER_NEW, established: "2026-02-01", method: "operator_manual" },
      ],
    });
    assert.equal(idx.get(OLD_ID).new_card_id, ANOTHER_NEW);
  });

  test("operator_revoke removes the alias from the index", () => {
    const idx = buildAliasIndex({
      aliases: [
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-01-01", method: "byte_collision" },
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-02-01", method: "operator_revoke" },
      ],
    });
    assert.equal(idx.get(OLD_ID), undefined);
  });

  test("revoke followed by re-establish brings the alias back", () => {
    const idx = buildAliasIndex({
      aliases: [
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-01-01", method: "byte_collision" },
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-02-01", method: "operator_revoke" },
        { old_card_id: OLD_ID, new_card_id: ANOTHER_NEW, established: "2026-03-01", method: "operator_manual" },
      ],
    });
    assert.equal(idx.get(OLD_ID).new_card_id, ANOTHER_NEW);
  });

  test("skips malformed rows without throwing", () => {
    const idx = buildAliasIndex({
      aliases: [
        { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-01-01", method: "byte_collision" },
        { /* missing old_card_id */ new_card_id: ANOTHER_NEW },
        null,
        "not an object",
        { old_card_id: ANOTHER_OLD, new_card_id: ANOTHER_NEW, method: "byte_collision" },
      ],
    });
    assert.equal(idx.size, 2);
    assert.equal(idx.get(OLD_ID).new_card_id, NEW_ID);
    assert.equal(idx.get(ANOTHER_OLD).new_card_id, ANOTHER_NEW);
  });
});

describe("parseCardPath", () => {
  test("extracts card_id from /card/<id>", () => {
    assert.equal(parseCardPath(`/card/${OLD_ID}`), OLD_ID);
  });

  test("accepts trailing slash", () => {
    assert.equal(parseCardPath(`/card/${OLD_ID}/`), OLD_ID);
  });

  test("rejects invalid card_id format", () => {
    assert.equal(parseCardPath("/card/INVALID"), null);
    assert.equal(parseCardPath("/card/aa3097b4c549a67"), null);  // 15 chars
    assert.equal(parseCardPath("/card/aa3097b4c549a67ab"), null); // 17 chars
    assert.equal(parseCardPath("/card/AA3097B4C549A67A"), null);  // uppercase
  });

  test("rejects non-card paths", () => {
    assert.equal(parseCardPath("/"), null);
    assert.equal(parseCardPath("/pdf/aa3097b4c549a67a.pdf"), null);
    assert.equal(parseCardPath("/cards"), null);
    assert.equal(parseCardPath(`/card/${OLD_ID}/extra`), null);
  });
});

describe("parsePdfPath", () => {
  test("extracts card_id from /pdf/<id>.pdf", () => {
    assert.equal(parsePdfPath(`/pdf/${OLD_ID}.pdf`), OLD_ID);
  });

  test("rejects invalid formats", () => {
    assert.equal(parsePdfPath(`/pdf/${OLD_ID}`), null); // no .pdf
    assert.equal(parsePdfPath("/pdf/INVALID.pdf"), null);
    assert.equal(parsePdfPath("/card/aa3097b4c549a67a"), null);
  });
});

describe("resolveAlias", () => {
  test("returns new_card_id when alias exists", () => {
    const idx = buildAliasIndex(SAMPLE);
    assert.equal(resolveAlias(idx, OLD_ID), NEW_ID);
  });

  test("returns null when no alias", () => {
    const idx = buildAliasIndex(SAMPLE);
    assert.equal(resolveAlias(idx, NEW_ID), null);
    assert.equal(resolveAlias(idx, "ffffffffffffffff"), null);
  });

  test("returns null on empty index", () => {
    assert.equal(resolveAlias(new Map(), OLD_ID), null);
  });
});

describe("tryHandleCardAlias", () => {
  function req(path) {
    return new Request(`https://example.com${path}`);
  }

  test("returns 301 for aliased card_id", () => {
    const idx = buildAliasIndex(SAMPLE);
    const resp = tryHandleCardAlias(req(`/card/${OLD_ID}`), idx);
    assert.ok(resp, "expected non-null response");
    assert.equal(resp.status, 301);
    assert.equal(resp.headers.get("Location"), `/card/${NEW_ID}`);
    assert.equal(resp.headers.get("X-Pursue-Aliased-From"), OLD_ID);
  });

  test("preserves trailing slash on redirect target", () => {
    const idx = buildAliasIndex(SAMPLE);
    const resp = tryHandleCardAlias(req(`/card/${OLD_ID}/`), idx);
    assert.equal(resp.status, 301);
    assert.equal(resp.headers.get("Location"), `/card/${NEW_ID}/`);
  });

  test("returns null when card_id is not aliased (falls through)", () => {
    const idx = buildAliasIndex(SAMPLE);
    assert.equal(tryHandleCardAlias(req(`/card/${NEW_ID}`), idx), null);
    assert.equal(tryHandleCardAlias(req("/card/ffffffffffffffff"), idx), null);
  });

  test("returns null for non-card paths", () => {
    const idx = buildAliasIndex(SAMPLE);
    assert.equal(tryHandleCardAlias(req("/"), idx), null);
    assert.equal(tryHandleCardAlias(req("/pdf/aa3097b4c549a67a.pdf"), idx), null);
    assert.equal(tryHandleCardAlias(req("/atlas"), idx), null);
  });

  test("returns null for invalid card_id format", () => {
    const idx = buildAliasIndex(SAMPLE);
    assert.equal(tryHandleCardAlias(req("/card/INVALID"), idx), null);
  });

  test("response body explains the redirect (for human eyeballs hitting the URL)", async () => {
    const idx = buildAliasIndex(SAMPLE);
    const resp = tryHandleCardAlias(req(`/card/${OLD_ID}`), idx);
    const text = await resp.text();
    assert.match(text, /re-cataloged|aliased/i);
    assert.match(text, new RegExp(NEW_ID));
  });
});
