// Tests for the security-header wrapper.
//
// CSP is intentionally NOT added in this sprint — see the comment in
// worker/index.js. The chat-interface plan picks it up because card detail
// pages iframe war.gov PDFs (frame-src https://www.war.gov needed).

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import { withSecurityHeaders } from "../index.js";

/**
 * Pull a CSP directive (e.g. "script-src 'self' 'unsafe-inline' ...") out of
 * a CSP header string. Returns the directive line with its name, or
 * ``undefined`` if the directive is absent. Centralizes the parse logic so
 * the per-token regression locks below stay one-liners (nayru P2 #3).
 */
function getCspDirective(csp, name) {
  return csp
    .split(";")
    .map((d) => d.trim())
    .find((d) => d.startsWith(`${name} `));
}

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

  // CSP regression-locks: the script-src directive must keep both
  // 'unsafe-eval' (regl-scatterplot compiles WebGL shaders via Function())
  // and the Cloudflare Insights beacon origin. A future tightening that
  // drops either silently breaks the /atlas page, so freeze the contract
  // here. See worker/index.js::CSP_VALUE for the rationale comment.
  test("CSP script-src includes 'unsafe-eval' for regl/WebGL shader compile", () => {
    const r = withSecurityHeaders(new Response("ok"));
    const csp = r.headers.get("Content-Security-Policy") ?? "";
    const scriptSrc = getCspDirective(csp, "script-src");
    assert.ok(scriptSrc, "CSP must contain a script-src directive");
    assert.ok(
      scriptSrc.includes("'unsafe-eval'"),
      `script-src must include 'unsafe-eval' (got: ${scriptSrc})`,
    );
  });

  test("CSP script-src allows Cloudflare Insights beacon origin", () => {
    const r = withSecurityHeaders(new Response("ok"));
    const csp = r.headers.get("Content-Security-Policy") ?? "";
    const scriptSrc = getCspDirective(csp, "script-src");
    assert.ok(scriptSrc, "CSP must contain a script-src directive");
    assert.ok(
      scriptSrc.includes("https://static.cloudflareinsights.com"),
      `script-src must include https://static.cloudflareinsights.com (got: ${scriptSrc})`,
    );
  });

  // Beacon SCRIPT loads from `static.cloudflareinsights.com` (script-src,
  // above), but the RUM telemetry POST egresses to
  // `https://cloudflareinsights.com/cdn-cgi/rum` — a *different* subdomain
  // governed by `connect-src`. Without this token the beacon script loads
  // and then the POST is blocked, surfacing as a second CSP violation on
  // a different directive. Lock the connect-src contract here so a future
  // narrowing of the connect-src list can't silently re-break analytics.
  test("CSP connect-src allows Cloudflare Insights RUM endpoint", () => {
    const r = withSecurityHeaders(new Response("ok"));
    const csp = r.headers.get("Content-Security-Policy") ?? "";
    const connectSrc = getCspDirective(csp, "connect-src");
    assert.ok(connectSrc, "CSP must contain a connect-src directive");
    assert.ok(
      connectSrc.includes("https://cloudflareinsights.com"),
      `connect-src must include https://cloudflareinsights.com (got: ${connectSrc})`,
    );
  });

  // Regression: PDFs are now self-hosted via R2 (route /pdf/<id>.pdf in
  // worker/index.js), so frame-src no longer needs to allowlist war.gov.
  // Lock the same-origin posture here so a future regression that adds
  // back the cross-origin permission has to confront this test. (See
  // SECURITY.md and docs/architecture.md for the framing-block context.)
  test("CSP frame-src is 'self' only (war.gov no longer needs framing)", () => {
    const r = withSecurityHeaders(new Response("ok"));
    const csp = r.headers.get("Content-Security-Policy") ?? "";
    const frameSrc = getCspDirective(csp, "frame-src");
    assert.ok(frameSrc, "CSP must contain a frame-src directive");
    assert.ok(
      !frameSrc.includes("war.gov"),
      `frame-src must NOT include war.gov post-self-host (got: ${frameSrc})`,
    );
    assert.ok(
      frameSrc.includes("'self'"),
      `frame-src must include 'self' (got: ${frameSrc})`,
    );
  });

  // A/V cards play from our own R2 mirror via same-origin <video>/<audio>
  // at /video/<card_id>.mp4 (DVIDS 404'd the upstream sources in 2026-07).
  // media-src is pinned to 'self' so a future default-src refactor can't
  // silently break playback. Regression-lock the same-origin posture.
  test("CSP media-src is 'self' (R2-served <video>/<audio> playback)", () => {
    const r = withSecurityHeaders(new Response("ok"));
    const csp = r.headers.get("Content-Security-Policy") ?? "";
    const mediaSrc = getCspDirective(csp, "media-src");
    assert.ok(mediaSrc, "CSP must contain a media-src directive");
    assert.ok(
      mediaSrc.includes("'self'"),
      `media-src must include 'self' (got: ${mediaSrc})`,
    );
  });
});
