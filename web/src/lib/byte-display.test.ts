import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  _ARCHIVE_EXT_ALLOWLIST,
  archiveHrefFromKey,
  categoryClass,
  categorySlug,
  formatBytes,
  sizeDeltaPct,
} from "./byte-display.ts";

// Imported from the worker so the lockstep test below pins the
// two allowlists to agree byte-for-byte. Any drift fails CI before
// it can ship a build/runtime mismatch (PR #79).
import { ARCHIVE_EXT_TO_CONTENT_TYPE } from "../../../worker/pdf.js";

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

describe("archiveHrefFromKey", () => {
  test("canonical shape produces a leading-slash URL path", () => {
    const sha = "a".repeat(64);
    assert.equal(archiveHrefFromKey(`archive/${sha}.pdf`), `/archive/${sha}.pdf`);
  });

  test("accepts multiple extensions (pdf, mp4, jpg)", () => {
    const sha = "b".repeat(64);
    assert.equal(archiveHrefFromKey(`archive/${sha}.mp4`), `/archive/${sha}.mp4`);
    assert.equal(archiveHrefFromKey(`archive/${sha}.jpg`), `/archive/${sha}.jpg`);
  });

  test("rejects path traversal in the key", () => {
    assert.throws(() => archiveHrefFromKey("archive/../etc/passwd"));
  });

  test("rejects non-archive prefix", () => {
    const sha = "c".repeat(64);
    assert.throws(() => archiveHrefFromKey(`r2://archive/${sha}.pdf`));
  });

  test("rejects malformed sha (too short)", () => {
    assert.throws(() => archiveHrefFromKey("archive/deadbeef.pdf"));
  });

  test("rejects uppercase sha", () => {
    const upper = "A".repeat(64);
    assert.throws(() => archiveHrefFromKey(`archive/${upper}.pdf`));
  });

  test("rejects missing extension", () => {
    const sha = "d".repeat(64);
    assert.throws(() => archiveHrefFromKey(`archive/${sha}`));
  });

  test("allowlist matches worker's ARCHIVE_EXT_TO_CONTENT_TYPE byte-for-byte", () => {
    // PR #79: the consumer-side regex and the
    // worker's content-type map MUST stay in lockstep. A unilateral
    // edit on either side would otherwise let an extension pass
    // the build but 404 at runtime (or vice versa). This test
    // imports both sources of truth and asserts the union matches.
    const workerExts = new Set(Object.keys(ARCHIVE_EXT_TO_CONTENT_TYPE));
    const consumerExts = new Set(_ARCHIVE_EXT_ALLOWLIST);
    assert.deepEqual(
      [...workerExts].sort(),
      [...consumerExts].sort(),
      `extension allowlist drift between worker (${[...workerExts].sort()}) ` +
      `and consumer (${[...consumerExts].sort()}). Update BOTH ` +
      `worker/pdf.js:ARCHIVE_EXT_TO_CONTENT_TYPE AND ` +
      `web/src/lib/byte-display.ts:ARCHIVE_KEY_PATTERN + _ARCHIVE_EXT_ALLOWLIST.`,
    );
  });

  test("regex accepts every extension in the allowlist", () => {
    // Smoke-check the regex parses every entry. Catches a mismatch
    // between _ARCHIVE_EXT_ALLOWLIST and the inline pattern.
    const sha = "1".repeat(64);
    for (const ext of _ARCHIVE_EXT_ALLOWLIST) {
      assert.doesNotThrow(
        () => archiveHrefFromKey(`archive/${sha}.${ext}`),
        `regex should accept .${ext}`,
      );
    }
  });

  test("rejects out-of-allowlist extensions (.exe, .html, typo'd .pfd)", () => {
    // PR #79: regex narrowed
    // from `[a-z0-9]+` to a worker-served allowlist. Catches both
    // attacker-shaped extensions and operator typos that produce
    // 404s instead of failing the build.
    const sha = "e".repeat(64);
    assert.throws(() => archiveHrefFromKey(`archive/${sha}.exe`));
    assert.throws(() => archiveHrefFromKey(`archive/${sha}.html`));
    assert.throws(() => archiveHrefFromKey(`archive/${sha}.pfd`));
  });

  test("error message names the bad key", () => {
    try {
      archiveHrefFromKey("garbage");
    } catch (e) {
      assert.match(String(e), /"garbage"/);
    }
  });
});

describe("categoryClass", () => {
  test("each v2 category returns its altered-cat-<name> class", () => {
    assert.equal(categoryClass("re_processing"), "altered-cat-re_processing");
    assert.equal(categoryClass("procedural_correction"), "altered-cat-procedural_correction");
    assert.equal(categoryClass("content_change"), "altered-cat-content_change");
  });

  test("null / undefined / unknown fall back to altered-cat-unverified", () => {
    assert.equal(categoryClass(null), "altered-cat-unverified");
    assert.equal(categoryClass(undefined), "altered-cat-unverified");
    assert.equal(categoryClass("garbage"), "altered-cat-unverified");
    assert.equal(categoryClass(""), "altered-cat-unverified");
  });

  test("rejects v1-vocab values (defense-in-depth: schema bumped)", () => {
    // confirmed_content_change / false_positive / unsure are v1 verdicts,
    // not v2 categories. Don't render them as a category-class.
    assert.equal(categoryClass("confirmed_content_change"), "altered-cat-unverified");
    assert.equal(categoryClass("false_positive"), "altered-cat-unverified");
  });

  test("guards against CSS-injection-shaped strings", () => {
    // The whitelist closes off any operator-typo string from
    // producing a stray class attribute (PR #79).
    assert.equal(categoryClass("content_change; color: red"), "altered-cat-unverified");
    assert.equal(categoryClass("<script>alert(1)</script>"), "altered-cat-unverified");
  });
});

describe("categorySlug", () => {
  test("each v2 category passes through unchanged", () => {
    assert.equal(categorySlug("re_processing"), "re_processing");
    assert.equal(categorySlug("procedural_correction"), "procedural_correction");
    assert.equal(categorySlug("content_change"), "content_change");
  });

  test("null / undefined / garbage fall back to 'unverified'", () => {
    // 'unverified' matches the pill button's data-filter value.
    assert.equal(categorySlug(null), "unverified");
    assert.equal(categorySlug(undefined), "unverified");
    assert.equal(categorySlug(""), "unverified");
    assert.equal(categorySlug("contant_change"), "unverified");
  });

  test("rejects v1-vocab values (don't leak into the data attribute)", () => {
    // The pill filter only knows the v2 categories + unverified.
    // A v1-leakage row would otherwise be unfilterable except via 'all'.
    assert.equal(categorySlug("false_positive"), "unverified");
    assert.equal(categorySlug("confirmed_content_change"), "unverified");
  });
});
