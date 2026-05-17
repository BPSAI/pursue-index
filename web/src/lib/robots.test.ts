/**
 * Tests for the robots.txt content builder.
 *
 * The dynamic robots.txt page delegates content generation here so it
 * can be unit-tested without spinning up Astro. The builder takes the
 * site origin + a sitemap URL and returns the textual robots.txt body.
 *
 * Sprint 1.1 (2026-05-17) — replaced the single allow-all AI_CRAWLERS
 * list with a typed Allow/Block split that mirrors the operator's
 * stated policy: surface our content (search bots, user-fetchers,
 * archivers) is Allow; training-data ingestion (LLM pretraining
 * crawlers) is Block.
 *
 * Run with: `node --test src/lib/robots.test.ts`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { buildRobotsTxt, AI_ALLOW, AI_BLOCK } from "./robots.ts";

// --- List membership ---------------------------------------------------

test("AI_ALLOW lists the operator-approved surface bots (search/user/archivers)", () => {
  // Each entry is a bot whose stated purpose is to surface our content
  // in an AI assistant / AI search result / regular search result OR
  // is an archiver for preservation. Order here mirrors robots.ts for
  // diff readability.
  const REQUIRED_ALLOW = [
    // OpenAI
    "ChatGPT-User",
    "OAI-SearchBot",
    // Anthropic
    "Claude-User",
    "Claude-SearchBot",
    // Google
    "Googlebot",
    // Microsoft / Bing
    "Bingbot",
    // Apple
    "Applebot",
    // Perplexity
    "PerplexityBot",
    "Perplexity-User",
    // DuckDuckGo
    "DuckAssistBot",
    // Mistral
    "MistralAI-User",
    // Meta — user-fetcher only
    "Meta-ExternalFetcher",
    // Huawei
    "PetalBot",
    // Amazon — granular allow
    "Amzn-SearchBot",
    "Amzn-User",
    // Google Vertex (opt-in customer RAG)
    "Google-CloudVertexBot",
    // ProRata (pay-publishers RAG)
    "ProRataInc",
    // Cloudflare
    "Cloudflare Crawler",
    // Agent browser-as-a-service
    "Anchor Browser",
    "Manus Bot",
    // Archivers
    "archive.org_bot",
    "Arquivo Web Crawler",
  ];
  for (const name of REQUIRED_ALLOW) {
    assert.ok(
      AI_ALLOW.includes(name),
      `Expected AI_ALLOW to include ${JSON.stringify(name)}`,
    );
  }
  assert.equal(AI_ALLOW.length, REQUIRED_ALLOW.length);
});

test("AI_BLOCK lists the operator-rejected training-corpus bots", () => {
  // Each entry is a bot whose stated purpose is bulk corpus ingestion
  // for LLM pretraining, foundation-model training, or generic
  // training-data licensing — content goes into model weights, not
  // into a citation answer for a user's query.
  const REQUIRED_BLOCK = [
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
    "Applebot-Extended",
    "PanguBot",
    "Bytespider",
    "TikTok Spider",
    "CCBot",
    "Meta-ExternalAgent",
    "FacebookBot",
    "Amazonbot",
    "Diffbot",
    "ImagesiftBot",
    "img2dataset",
    "cohere-training-data-crawler",
    "Terracotta Bot",
    "Timpibot",
    "Novellum AI Crawl",
  ];
  for (const name of REQUIRED_BLOCK) {
    assert.ok(
      AI_BLOCK.includes(name),
      `Expected AI_BLOCK to include ${JSON.stringify(name)}`,
    );
  }
  assert.equal(AI_BLOCK.length, REQUIRED_BLOCK.length);
});

test("AI_ALLOW and AI_BLOCK are mutually exclusive (no bot in both lists)", () => {
  // Mutual exclusion guard: a bot must be either surfaced or blocked,
  // never both. The Terracotta Bot case (operator flipped Allow → Block
  // late) is the canonical reason this guard exists.
  const allowSet = new Set(AI_ALLOW);
  const overlap = AI_BLOCK.filter((name) => allowSet.has(name));
  assert.deepEqual(
    overlap,
    [],
    `Found bots present in BOTH AI_ALLOW and AI_BLOCK: ${overlap.join(", ")}`,
  );
});

test("AI_ALLOW and AI_BLOCK have no duplicate entries within their own list", () => {
  // De-dupe guard — easy to miss when manually editing.
  assert.equal(
    new Set(AI_ALLOW).size,
    AI_ALLOW.length,
    "AI_ALLOW contains duplicates",
  );
  assert.equal(
    new Set(AI_BLOCK).size,
    AI_BLOCK.length,
    "AI_BLOCK contains duplicates",
  );
});

// --- Critical-bot spot checks -----------------------------------------

test("critical training bots are in AI_BLOCK", () => {
  // These are the bots whose Allow rule in the prior version was the
  // visible contradiction with operator policy.
  assert.ok(AI_BLOCK.includes("ClaudeBot"), "ClaudeBot must be blocked");
  assert.ok(AI_BLOCK.includes("GPTBot"), "GPTBot must be blocked");
  assert.ok(
    AI_BLOCK.includes("Google-Extended"),
    "Google-Extended must be blocked",
  );
  assert.ok(
    AI_BLOCK.includes("Applebot-Extended"),
    "Applebot-Extended must be blocked",
  );
  assert.ok(AI_BLOCK.includes("PanguBot"), "PanguBot must be blocked");
  assert.ok(AI_BLOCK.includes("CCBot"), "CCBot must be blocked");
  assert.ok(AI_BLOCK.includes("Bytespider"), "Bytespider must be blocked");
  assert.ok(
    AI_BLOCK.includes("Meta-ExternalAgent"),
    "Meta-ExternalAgent must be blocked",
  );
});

test("critical surface bots are in AI_ALLOW", () => {
  // The bots that the operator explicitly wants to keep surfacing
  // content to user-driven sessions.
  assert.ok(
    AI_ALLOW.includes("ChatGPT-User"),
    "ChatGPT-User must be allowed",
  );
  assert.ok(AI_ALLOW.includes("Claude-User"), "Claude-User must be allowed");
  assert.ok(AI_ALLOW.includes("Googlebot"), "Googlebot must be allowed");
  assert.ok(AI_ALLOW.includes("Bingbot"), "Bingbot must be allowed");
  assert.ok(AI_ALLOW.includes("Applebot"), "Applebot must be allowed");
  assert.ok(
    AI_ALLOW.includes("PerplexityBot"),
    "PerplexityBot must be allowed",
  );
  assert.ok(
    AI_ALLOW.includes("archive.org_bot"),
    "archive.org_bot must be allowed",
  );
});

// --- Rendered output --------------------------------------------------

test("buildRobotsTxt emits a Disallow / block for every AI_BLOCK entry", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  for (const name of AI_BLOCK) {
    // Each blocked crawler needs its own User-agent block with
    // Disallow: / so a parser can find an authoritative rule.
    const uaPattern = new RegExp(
      `^User-agent: ${escapeRegex(name)}\\s*$`,
      "m",
    );
    assert.match(body, uaPattern, `Missing User-agent block for ${name}`);
    // Spot-check via positional assertion: the block's Disallow rule
    // must directly follow the User-agent line.
    const idx = body.indexOf(`User-agent: ${name}\n`);
    assert.ok(
      idx >= 0,
      `User-agent: ${name} must be followed by newline`,
    );
    const rest = body.slice(idx);
    assert.match(
      rest.split("\n").slice(0, 3).join("\n"),
      /Disallow: \/$/m,
      `Expected Disallow: / immediately under User-agent: ${name}`,
    );
  }
});

test("buildRobotsTxt emits an Allow / block for every AI_ALLOW entry", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  for (const name of AI_ALLOW) {
    const uaPattern = new RegExp(
      `^User-agent: ${escapeRegex(name)}\\s*$`,
      "m",
    );
    assert.match(body, uaPattern, `Missing User-agent block for ${name}`);
    const idx = body.indexOf(`User-agent: ${name}\n`);
    assert.ok(idx >= 0);
    const rest = body.slice(idx);
    const window = rest.split("\n").slice(0, 3).join("\n");
    assert.match(
      window,
      /Allow: \/$/m,
      `Expected Allow: / immediately under User-agent: ${name}`,
    );
  }
});

test("buildRobotsTxt orders AI_BLOCK entries before AI_ALLOW entries", () => {
  // RFC 9309 says most parsers honor first match. Listing Disallow
  // blocks first means a training crawler reading top-down hits its
  // own rule before hitting any other Allow rule.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const firstBlockIdx = body.indexOf(`User-agent: ${AI_BLOCK[0]}`);
  const firstAllowIdx = body.indexOf(`User-agent: ${AI_ALLOW[0]}`);
  assert.ok(firstBlockIdx >= 0 && firstAllowIdx >= 0);
  assert.ok(
    firstBlockIdx < firstAllowIdx,
    "AI_BLOCK section must come before AI_ALLOW section",
  );
});

test("buildRobotsTxt distinguishes Allow/Disallow correctly for paired bot families", () => {
  // The whole point of Sprint 1.1: a vendor's user bot and its
  // training bot must end up on opposite sides of the policy. Spot
  // check the key pairs explicitly.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });

  const pairs: Array<[string, "Allow" | "Disallow"]> = [
    ["GPTBot", "Disallow"],
    ["ChatGPT-User", "Allow"],
    ["ClaudeBot", "Disallow"],
    ["Claude-User", "Allow"],
    ["Google-Extended", "Disallow"],
    ["Googlebot", "Allow"],
    ["Applebot-Extended", "Disallow"],
    ["Applebot", "Allow"],
    ["PanguBot", "Disallow"],
    ["PetalBot", "Allow"],
    ["Meta-ExternalAgent", "Disallow"],
    ["Meta-ExternalFetcher", "Allow"],
    ["Amazonbot", "Disallow"],
    ["Amzn-SearchBot", "Allow"],
  ];
  for (const [bot, action] of pairs) {
    const idx = body.indexOf(`User-agent: ${bot}\n`);
    assert.ok(idx >= 0, `Missing User-agent: ${bot}`);
    const window = body.slice(idx).split("\n").slice(0, 3).join("\n");
    assert.match(
      window,
      new RegExp(`^${action}: /$`, "m"),
      `Expected ${action}: / for ${bot}, got: ${window}`,
    );
  }
});

test("buildRobotsTxt preserves the wildcard fallback with /api/ Disallow", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.match(body, /^User-agent: \*$/m);
  assert.match(body, /^Disallow: \/api\//m);
});

test("buildRobotsTxt includes Sitemap and Host directives", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.match(
    body,
    /^Sitemap: https:\/\/pursueindex\.com\/sitemap-index\.xml$/m,
  );
  assert.match(body, /^Host: pursueindex\.com$/m);
});

test("buildRobotsTxt body ends with a trailing newline", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.ok(body.endsWith("\n"), "robots.txt should end with newline");
});

test("buildRobotsTxt accepts a custom siteOrigin", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://example.org" });
  assert.match(
    body,
    /^Sitemap: https:\/\/example\.org\/sitemap-index\.xml$/m,
  );
  assert.match(body, /^Host: example\.org$/m);
});

test("buildRobotsTxt issues exactly one Allow/Disallow rule per AI block", () => {
  // Sanity: total Allow: / lines = AI_ALLOW.length + 1 (wildcard).
  // Total Disallow: / lines = AI_BLOCK.length. /api/ Disallow appears
  // only in the wildcard block.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const allowSlashCount = (body.match(/^Allow: \/$/gm) ?? []).length;
  const disallowSlashCount = (body.match(/^Disallow: \/$/gm) ?? []).length;
  const disallowApiCount = (body.match(/^Disallow: \/api\//gm) ?? []).length;
  assert.equal(
    allowSlashCount,
    AI_ALLOW.length + 1,
    "Allow: / count should be AI_ALLOW.length + 1 (wildcard)",
  );
  assert.equal(
    disallowSlashCount,
    AI_BLOCK.length,
    "Disallow: / count should match AI_BLOCK.length",
  );
  assert.equal(
    disallowApiCount,
    1,
    "Disallow: /api/ should only appear once (wildcard block)",
  );
});

// --- helpers ---------------------------------------------------------

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
