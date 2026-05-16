/**
 * Tests for the robots.txt content builder.
 *
 * The dynamic robots.txt page delegates content generation here so it
 * can be unit-tested without spinning up Astro. The builder takes the
 * site origin + a sitemap URL and returns the textual robots.txt body.
 *
 * Run with: `node --test src/lib/robots.test.ts`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildRobotsTxt, AI_CRAWLERS } from "./robots.ts";

test("AI_CRAWLERS includes the 27 named AI-crawler user-agents", () => {
  // The Sprint 1 plan enumerates every AI crawler that should be
  // explicitly allowed. The full list is canonical here. Adding/
  // removing names is a deliberate operator decision and should
  // surface as a test diff.
  const REQUIRED = [
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-Web",
    "anthropic-ai",
    "ClaudeBot-User",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "GoogleOther",
    "Meta-ExternalAgent",
    "Meta-ExternalFetcher",
    "FacebookBot",
    "Applebot-Extended",
    "Applebot",
    "Bytespider",
    "CCBot",
    "cohere-ai",
    "DuckAssistBot",
    "Mistral-AI",
    "xAI",
    "Grok",
    "Diffbot",
    "Amazonbot",
    "YouBot",
    "PetalBot",
  ];
  for (const name of REQUIRED) {
    assert.ok(
      AI_CRAWLERS.includes(name),
      `Expected AI_CRAWLERS to include ${JSON.stringify(name)}`,
    );
  }
  assert.equal(AI_CRAWLERS.length, REQUIRED.length);
});

test("buildRobotsTxt names every AI crawler with an Allow rule", () => {
  const body = buildRobotsTxt({
    siteOrigin: "https://pursueindex.com",
  });
  for (const name of AI_CRAWLERS) {
    // Each crawler has a `User-agent:` block; verify the block names
    // it explicitly.
    assert.match(
      body,
      new RegExp(`^User-agent: ${name}\\s*$`, "m"),
      `Missing User-agent block for ${name}`,
    );
  }
});

test("buildRobotsTxt preserves the consolidated wildcard + Disallow /api/", () => {
  const body = buildRobotsTxt({
    siteOrigin: "https://pursueindex.com",
  });
  // The pre-existing wildcard fallback stays so non-AI crawlers
  // continue to behave as before.
  assert.match(body, /^User-agent: \*$/m);
  assert.match(body, /^Disallow: \/api\//m);
});

test("buildRobotsTxt includes Sitemap and Host directives", () => {
  const body = buildRobotsTxt({
    siteOrigin: "https://pursueindex.com",
  });
  assert.match(body, /^Sitemap: https:\/\/pursueindex\.com\/sitemap-index\.xml$/m);
  assert.match(body, /^Host: pursueindex\.com$/m);
});

test("buildRobotsTxt issues an Allow: / per AI crawler block", () => {
  const body = buildRobotsTxt({
    siteOrigin: "https://pursueindex.com",
  });
  // Each AI-crawler block must have an explicit Allow: / so a parser
  // doesn't fall through to the wildcard's Disallow rule for
  // crawler-specific path constraints. /api/ remains disallowed
  // globally via the wildcard.
  const allowCount = (body.match(/^Allow: \//gm) ?? []).length;
  // One per named AI crawler + one in the wildcard block.
  assert.ok(allowCount >= AI_CRAWLERS.length);
});

test("buildRobotsTxt body ends with a trailing newline", () => {
  const body = buildRobotsTxt({
    siteOrigin: "https://pursueindex.com",
  });
  assert.ok(body.endsWith("\n"), "robots.txt should end with newline");
});

test("buildRobotsTxt accepts a custom siteOrigin", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://example.org" });
  assert.match(body, /^Sitemap: https:\/\/example\.org\/sitemap-index\.xml$/m);
  assert.match(body, /^Host: example\.org$/m);
});
