// Tests for worker/index.js cookie parsing.
//
// The original implementation used `cookie.includes("preview=bps-launch")`
// which matches decoy cookies like `notpreview=bps-launchfoo`. These tests
// pin the parser to the proper name=value contract.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { hasPreviewCookie } from "../index.js";

function reqWithCookie(cookieHeader) {
  return new Request("https://example.com/", {
    headers: cookieHeader == null ? {} : { Cookie: cookieHeader },
  });
}

describe("hasPreviewCookie", () => {
  test("missing Cookie header → false", () => {
    assert.equal(hasPreviewCookie(reqWithCookie(null)), false);
  });

  test("empty Cookie header → false", () => {
    assert.equal(hasPreviewCookie(reqWithCookie("")), false);
  });

  test("exact preview=bps-launch → true", () => {
    assert.equal(hasPreviewCookie(reqWithCookie("preview=bps-launch")), true);
  });

  test("preview=bps-launch alongside other cookies → true", () => {
    assert.equal(
      hasPreviewCookie(reqWithCookie("session=abc; preview=bps-launch; tz=UTC")),
      true,
    );
  });

  test("decoy notpreview=bps-launch → false", () => {
    // The naive substring check would match this; the proper parser must not.
    assert.equal(hasPreviewCookie(reqWithCookie("notpreview=bps-launch")), false);
  });

  test("decoy preview=bps-launch-evil → false", () => {
    // Suffix on the value must not count as a match.
    assert.equal(
      hasPreviewCookie(reqWithCookie("preview=bps-launch-evil")),
      false,
    );
  });

  test("decoy something=preview=bps-launch → false", () => {
    // A different cookie whose value happens to contain the literal must not match.
    assert.equal(
      hasPreviewCookie(reqWithCookie("something=preview=bps-launch")),
      false,
    );
  });

  test("preview=other → false", () => {
    assert.equal(hasPreviewCookie(reqWithCookie("preview=other")), false);
  });

  test("whitespace tolerance: ` preview=bps-launch` → true", () => {
    // Cookie spec lets servers send `name=value;name=value` with optional
    // single space after the semicolon. Tolerate that.
    assert.equal(hasPreviewCookie(reqWithCookie("a=1; preview=bps-launch")), true);
  });
});
