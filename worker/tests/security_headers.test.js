// Tests for the security-header wrapper.
//
// CSP is intentionally NOT added in this sprint — see the comment in
// worker/index.js. The chat-interface plan picks it up because card detail
// pages iframe war.gov PDFs (frame-src https://www.war.gov needed).

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { withSecurityHeaders } from "../index.js";

describe("withSecurityHeaders", () => {
  test("adds X-Content-Type-Options: nosniff", () => {
    const r = withSecurityHeaders(new Response("ok"));
    assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
  });

  test("adds Referrer-Policy: strict-origin-when-cross-origin", () => {
    const r = withSecurityHeaders(new Response("ok"));
    assert.equal(
      r.headers.get("Referrer-Policy"),
      "strict-origin-when-cross-origin",
    );
  });

  test("adds X-Frame-Options: SAMEORIGIN", () => {
    const r = withSecurityHeaders(new Response("ok"));
    assert.equal(r.headers.get("X-Frame-Options"), "SAMEORIGIN");
  });

  test("adds Permissions-Policy: interest-cohort=()", () => {
    const r = withSecurityHeaders(new Response("ok"));
    assert.equal(r.headers.get("Permissions-Policy"), "interest-cohort=()");
  });

  test("preserves status, body, and existing headers", async () => {
    const original = new Response("hello world", {
      status: 201,
      headers: { "Content-Type": "text/plain", "X-Custom": "keep" },
    });
    const wrapped = withSecurityHeaders(original);
    assert.equal(wrapped.status, 201);
    assert.equal(wrapped.headers.get("Content-Type"), "text/plain");
    assert.equal(wrapped.headers.get("X-Custom"), "keep");
    assert.equal(await wrapped.text(), "hello world");
  });

  test("does not clobber an explicit existing security header", () => {
    // Edge case: a downstream may set its own X-Frame-Options. Defer to it.
    const original = new Response("ok", {
      headers: { "X-Frame-Options": "DENY" },
    });
    const wrapped = withSecurityHeaders(original);
    assert.equal(wrapped.headers.get("X-Frame-Options"), "DENY");
  });
});
