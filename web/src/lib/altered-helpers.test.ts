import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { buildAlteredRows, type ByteHistoryEntry } from "./altered-helpers.ts";

function makeEntry(sha: string, size: number, ts: string): ByteHistoryEntry {
  return {
    byte_sha256: sha,
    byte_size: size,
    fetched_at: ts,
    archive_key: `archive/${sha}.pdf`,
    asset_filename: "doc.pdf",
    is_current: false,
  };
}

describe("buildAlteredRows", () => {
  test("skips cards not in the active manifest (covered by /removed)", () => {
    const byteHistory = {
      kept: [
        makeEntry("a".repeat(64), 100, "2026-05-14T00:00:00Z"),
        makeEntry("b".repeat(64), 200, "2026-05-12T00:00:00Z"),
      ],
      removed: [
        makeEntry("c".repeat(64), 100, "2026-05-14T00:00:00Z"),
        makeEntry("d".repeat(64), 200, "2026-05-12T00:00:00Z"),
      ],
    };
    const cards = [
      { card_id: "kept", title: "Kept", asset_type: "PDF" },
      // "removed" intentionally omitted from cards list
    ];
    const rows = buildAlteredRows(byteHistory, cards);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].card_id, "kept");
  });

  test("skips single-version cards defensively (extra guard)", () => {
    // build_byte_history.mjs already filters these out, but defense
    // in depth — buildAlteredRows shouldn't crash if a future caller
    // hands it a non-multi-sha entry.
    const byteHistory = {
      single: [makeEntry("a".repeat(64), 100, "2026-05-12T00:00:00Z")],
    };
    const cards = [{ card_id: "single", title: "Single", asset_type: "PDF" }];
    assert.deepEqual(buildAlteredRows(byteHistory, cards), []);
  });

  test("current_entry is entries[0] and oldest_entry is entries[length-1]", () => {
    // Relies on build_byte_history's newest-first contract. Test
    // pinning so a future re-order would surface here.
    const byteHistory = {
      x: [
        makeEntry("a".repeat(64), 100, "2026-05-14T00:00:00Z"),
        makeEntry("b".repeat(64), 200, "2026-05-12T00:00:00Z"),
      ],
    };
    const cards = [{ card_id: "x", title: "X", asset_type: "PDF" }];
    const [row] = buildAlteredRows(byteHistory, cards);
    assert.equal(row.current_entry.byte_size, 100);
    assert.equal(row.oldest_entry.byte_size, 200);
    assert.equal(row.total_versions, 2);
  });

  test("rows sort newest-edit first, then by title", () => {
    const byteHistory = {
      old_a: [
        makeEntry("1".repeat(64), 100, "2026-05-12T00:00:00Z"),
        makeEntry("2".repeat(64), 200, "2026-05-10T00:00:00Z"),
      ],
      old_b: [
        makeEntry("3".repeat(64), 100, "2026-05-14T00:00:00Z"),
        makeEntry("4".repeat(64), 200, "2026-05-13T00:00:00Z"),
      ],
      tie_z: [
        makeEntry("5".repeat(64), 100, "2026-05-14T00:00:00Z"),
        makeEntry("6".repeat(64), 200, "2026-05-13T00:00:00Z"),
      ],
    };
    const cards = [
      { card_id: "old_a", title: "Alpha", asset_type: "PDF" },
      { card_id: "old_b", title: "Beta", asset_type: "PDF" },
      { card_id: "tie_z", title: "Zulu", asset_type: "PDF" },
    ];
    const rows = buildAlteredRows(byteHistory, cards);
    // old_b (2026-05-14, Beta) before tie_z (2026-05-14, Zulu) — tie
    // broken by title ascending. old_a is last (older fetched_at).
    assert.deepEqual(
      rows.map((r) => r.card_id),
      ["old_b", "tie_z", "old_a"],
    );
  });

  test("empty input → empty output", () => {
    assert.deepEqual(buildAlteredRows({}, []), []);
  });
});
