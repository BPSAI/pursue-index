import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { formatBytes, sizeDeltaPct } from "./byte-display.ts";

describe("formatBytes", () => {
  test("bytes below 1KB render as B", () => {
    assert.equal(formatBytes(0), "0 B");
    assert.equal(formatBytes(512), "512 B");
    assert.equal(formatBytes(1023), "1023 B");
  });

  test("1KB boundary renders as KB", () => {
    assert.equal(formatBytes(1024), "1.0 KB");
  });

  test("kilobytes render with one decimal", () => {
    assert.equal(formatBytes(1024 * 100), "100.0 KB");
    assert.equal(formatBytes(124509), "121.6 KB"); // FBI Photo B008 post-edit
  });

  test("1MB boundary renders as MB", () => {
    assert.equal(formatBytes(1024 * 1024), "1.00 MB");
  });

  test("megabytes render with two decimals", () => {
    assert.equal(formatBytes(3354523), "3.20 MB"); // DOW-UAP-D020 pre-edit
    assert.equal(formatBytes(3698245), "3.53 MB"); // DOW-UAP-D020 post-edit
  });

  test("no locale separators leak into output", () => {
    // Stable across runners regardless of LC_ALL.
    const result = formatBytes(1024 * 1024 * 1234.56);
    assert.doesNotMatch(result, /[,_]/);
  });
});

describe("sizeDeltaPct", () => {
  test("positive delta renders with explicit + sign", () => {
    assert.equal(sizeDeltaPct(100, 110), "+10.0%");
  });

  test("negative delta renders with - sign", () => {
    assert.equal(sizeDeltaPct(100, 90), "-10.0%");
  });

  test("zero delta renders as +0.0%", () => {
    // The sign convention treats >=0 as +, so 0 → "+0.0%" not "0.0%".
    assert.equal(sizeDeltaPct(100, 100), "+0.0%");
  });

  test("zero prior returns +∞ sentinel (no NaN/Inf division)", () => {
    assert.equal(sizeDeltaPct(0, 100), "+∞");
    // Even when current is also zero, prior=0 still fires the sentinel
    // (we can't compute a meaningful percentage from 0→0).
    assert.equal(sizeDeltaPct(0, 0), "+∞");
  });

  test("FBI Photo B008 case (585686 → 124509)", () => {
    // Real registry case: -78.74...% — pinned to one decimal.
    assert.equal(sizeDeltaPct(585686, 124509), "-78.7%");
  });

  test("DOW-UAP-D020 Iraq case (3354523 → 3698245)", () => {
    assert.equal(sizeDeltaPct(3354523, 3698245), "+10.2%");
  });
});
